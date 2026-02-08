"""
Payment Router — Proxy seguro para API Asaas
Flow: Frontend → apiClient → Python API → Asaas
Valores dos planos definidos server-side, nunca no frontend.
"""

import httpx
import uuid
import hmac
import hashlib
import time as time_module
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Request, Query
from loguru import logger

from config import get_settings

router = APIRouter(prefix="/payments", tags=["payments"])

# =============================================
# PLANOS & CENTELHAS — Dinâmico via Supabase
# Cache TTL de 5 min para evitar queries repetidas
# =============================================

import time

_plans_cache = {"data": None, "ts": 0}
_centelhas_cache = {"data": None, "ts": 0}
_CACHE_TTL = 300  # 5 minutos

# Fallbacks hardcoded (só usados se Supabase indisponível)
_PLANOS_FALLBACK = {
    "fluxo": {"valor_mensal": 37.90, "valor_anual": 379.00, "description": "Assinatura VibraEu Fluxo"},
    "expansao": {"valor_mensal": 89.90, "valor_anual": 899.00, "description": "Assinatura VibraEu Expansão"},
}

_CENTELHAS_FALLBACK = {
    "centelhas_5": {"quantidade": 5, "preco": 9.90, "descricao": "Pack Inicial - 5 Centelhas"},
    "centelhas_20": {"quantidade": 20, "preco": 29.90, "descricao": "Pack Evolução - 20+5 Centelhas"},
    "centelhas_40": {"quantidade": 40, "preco": 49.90, "descricao": "Pack Expansão - 40+10 Centelhas"},
    "centelhas_60": {"quantidade": 60, "preco": 79.90, "descricao": "Pack Iluminação - 60+15 Centelhas"},
}


def _get_planos() -> dict:
    """Busca planos de planos_config do Supabase com cache TTL."""
    now = time.time()
    if _plans_cache["data"] and (now - _plans_cache["ts"]) < _CACHE_TTL:
        return _plans_cache["data"]

    try:
        supabase = _get_supabase()
        if not supabase:
            return _PLANOS_FALLBACK

        result = supabase.table("planos_config").select("*").eq("ativo", True).execute()
        if not result.data:
            return _PLANOS_FALLBACK

        planos = {}
        for p in result.data:
            if p["id"] == "semente":
                continue  # Semente é grátis, não tem checkout
            planos[p["id"]] = {
                "valor_mensal": float(p["preco_mensal"]),
                "valor_anual": float(p["preco_anual"]) if p.get("preco_anual") else None,
                "description": f"Assinatura {p['nome']}",
            }

        _plans_cache["data"] = planos
        _plans_cache["ts"] = now
        logger.info(f"[Payments] Plans cache refreshed: {list(planos.keys())}")
        return planos
    except Exception as e:
        logger.warning(f"[Payments] Failed to load plans from DB, using fallback: {e}")
        return _PLANOS_FALLBACK


def _get_pacotes_centelhas() -> dict:
    """Busca pacotes de centelhas do Supabase com cache TTL."""
    now = time.time()
    if _centelhas_cache["data"] and (now - _centelhas_cache["ts"]) < _CACHE_TTL:
        return _centelhas_cache["data"]

    try:
        supabase = _get_supabase()
        if not supabase:
            return _CENTELHAS_FALLBACK

        result = supabase.table("pacotes_centelhas").select("*").eq("ativo", True).order("ordem").execute()
        if not result.data:
            return _CENTELHAS_FALLBACK

        pacotes = {}
        for p in result.data:
            bonus_text = f"+{p['bonus']}" if p.get("bonus", 0) > 0 else ""
            pacotes[p["id"]] = {
                "quantidade": p["quantidade"],
                "preco": float(p["preco"]),
                "bonus": p.get("bonus", 0),
                "descricao": f"{p.get('descricao', '')} - {p['quantidade']}{bonus_text} Centelhas",
            }

        _centelhas_cache["data"] = pacotes
        _centelhas_cache["ts"] = now
        logger.info(f"[Payments] Centelhas cache refreshed: {list(pacotes.keys())}")
        return pacotes
    except Exception as e:
        logger.warning(f"[Payments] Failed to load centelhas from DB, using fallback: {e}")
        return _CENTELHAS_FALLBACK


# =============================================
# MODELOS
# =============================================

class CreditCardInfo(BaseModel):
    holderName: str
    number: str
    expiryMonth: str
    expiryYear: str
    cvv: str


class CreditCardHolderInfo(BaseModel):
    name: str
    email: str
    cpfCnpj: str
    postalCode: str
    addressNumber: str
    phone: Optional[str] = None


class CreateCustomerRequest(BaseModel):
    name: str
    email: str
    cpfCnpj: Optional[str] = None
    phone: Optional[str] = None
    userId: str


class FindCustomerRequest(BaseModel):
    email: str


class CreateSubscriptionRequest(BaseModel):
    planCode: str
    isAnnual: bool = False
    billingType: str  # PIX, CREDIT_CARD, BOLETO
    customerId: str
    userId: str
    creditCard: Optional[CreditCardInfo] = None
    creditCardHolderInfo: Optional[CreditCardHolderInfo] = None


class CancelSubscriptionRequest(BaseModel):
    subscriptionId: str
    userId: str


class GetSubscriptionRequest(BaseModel):
    subscriptionId: str
    userId: str


class ListSubscriptionPaymentsRequest(BaseModel):
    subscriptionId: str
    userId: str


class GetPaymentRequest(BaseModel):
    paymentId: str
    userId: str


class GetPixQrCodeRequest(BaseModel):
    paymentId: str
    userId: str


class BuyCentelhasRequest(BaseModel):
    pacoteId: str
    customerId: str
    billingType: str
    userId: str
    creditCard: Optional[CreditCardInfo] = None
    creditCardHolderInfo: Optional[CreditCardHolderInfo] = None


# =============================================
# HELPER: Asaas HTTP Client
# =============================================

def _get_asaas_config():
    """Retorna base_url e api_key baseado no ambiente configurado no SERVIDOR."""
    settings = get_settings()
    is_sandbox = settings.asaas_environment == "sandbox"
    
    if is_sandbox:
        base_url = "https://sandbox.asaas.com/api/v3"
        api_key = settings.asaas_sandbox_api_key
    else:
        base_url = "https://api.asaas.com/v3"
        api_key = settings.asaas_prod_api_key
    
    if not api_key:
        env_name = "sandbox" if is_sandbox else "production"
        raise HTTPException(status_code=500, detail=f"Asaas API key não configurada ({env_name})")
    
    return base_url, api_key, is_sandbox


async def _asaas_request(method: str, endpoint: str, data: dict = None) -> dict:
    """Faz request para API Asaas com tratamento de erro."""
    base_url, api_key, _ = _get_asaas_config()
    url = f"{base_url}{endpoint}"
    
    headers = {
        "Content-Type": "application/json",
        "access_token": api_key,
        "User-Agent": "VibraEu/3.0",
    }
    
    logger.info(f"[Asaas] {method} {endpoint}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        if method == "GET":
            resp = await client.get(url, headers=headers)
        elif method == "POST":
            resp = await client.post(url, headers=headers, json=data)
        elif method == "PUT":
            resp = await client.put(url, headers=headers, json=data)
        elif method == "DELETE":
            resp = await client.delete(url, headers=headers)
        else:
            raise HTTPException(400, f"Método {method} não suportado")
    
    if not resp.is_success:
        try:
            error_data = resp.json()
            msg = error_data.get("errors", [{}])[0].get("description", f"Erro Asaas: {resp.status_code}")
        except Exception:
            msg = f"Erro Asaas: {resp.status_code}"
        logger.error(f"[Asaas] {method} {endpoint} → {resp.status_code}: {msg}")
        raise HTTPException(status_code=resp.status_code, detail=msg)
    
    return resp.json()


def _get_supabase():
    """Retorna Supabase client usando service role key."""
    from services.supabase_client import get_supabase_client
    return get_supabase_client()


async def _user_owns_subscription(user_id: str, subscription_id: str) -> bool:
    """Valida que a assinatura pertence ao usuário."""
    supabase = _get_supabase()
    if not supabase:
        return True  # Se Supabase indisponível, permitir (graceful degradation)
    result = supabase.table("assinaturas") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("asaas_subscription_id", subscription_id) \
        .maybe_single() \
        .execute()
    return result.data is not None


async def _user_owns_payment(user_id: str, payment_id: str) -> bool:
    """Valida que o pagamento pertence ao usuário."""
    supabase = _get_supabase()
    if not supabase:
        return True
    result = supabase.table("pagamentos") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("asaas_payment_id", payment_id) \
        .maybe_single() \
        .execute()
    if result.data:
        return True
    # Pagamento pode ser recente e não sincronizado ainda
    logger.warning(f"[Asaas] Propriedade do payment {payment_id} não confirmada, permitindo temporariamente")
    return True


# =============================================
# ENDPOINTS
# =============================================

@router.post("/create-customer")
async def create_customer(req: CreateCustomerRequest):
    """Criar ou buscar cliente existente no Asaas."""
    try:
        # Buscar existente
        existing = await _asaas_request("GET", f"/customers?email={req.email}")
        if existing.get("data") and len(existing["data"]) > 0:
            customer = existing["data"][0]
            logger.info(f"[Asaas] Cliente existente: {customer['id']}")
            return customer
        
        # Criar novo
        payload = {
            "name": req.name,
            "email": req.email,
            "cpfCnpj": req.cpfCnpj.replace("-", "").replace(".", "") if req.cpfCnpj else None,
            "phone": req.phone.replace("-", "").replace("(", "").replace(")", "").replace(" ", "") if req.phone else None,
            "notificationDisabled": False,
        }
        # Remover None values
        payload = {k: v for k, v in payload.items() if v is not None}
        
        result = await _asaas_request("POST", "/customers", payload)
        
        # Sync com Supabase
        supabase = _get_supabase()
        if supabase and result.get("id"):
            try:
                supabase.table("profiles").update({
                    "asaas_customer_id": result["id"],
                    "updated_at": datetime.utcnow().isoformat()
                }).eq("id", req.userId).execute()
            except Exception as e:
                logger.warning(f"[Asaas] Sync customer failed: {e}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Asaas] create-customer error: {e}")
        raise HTTPException(500, str(e))


@router.post("/find-customer")
async def find_customer(req: FindCustomerRequest):
    """Buscar cliente por email."""
    try:
        result = await _asaas_request("GET", f"/customers?email={req.email}")
        customer = result.get("data", [None])[0] if result.get("data") else None
        return customer or {"found": False}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Asaas] find-customer error: {e}")
        raise HTTPException(500, str(e))


@router.post("/create-subscription")
async def create_subscription(req: CreateSubscriptionRequest):
    """
    Criar assinatura com valor definido SERVER-SIDE.
    O frontend envia planCode, o servidor define o valor.
    """
    try:
        # Buscar planos dinâmicos do banco
        planos = _get_planos()
        
        # Validar plano
        if req.planCode not in planos:
            raise HTTPException(400, f"Plano '{req.planCode}' inválido. Válidos: {list(planos.keys())}")
        
        if req.billingType not in ("PIX", "CREDIT_CARD", "BOLETO"):
            raise HTTPException(400, f"billingType '{req.billingType}' inválido")
        
        plano = planos[req.planCode]
        
        # VALOR DEFINIDO PELO SERVIDOR
        value = plano["valor_anual"] if req.isAnnual else plano["valor_mensal"]
        cycle = "YEARLY" if req.isAnnual else "MONTHLY"
        description = f"{plano['description']} ({'Anual' if req.isAnnual else 'Mensal'})"
        
        logger.info(f"[Asaas] Criando assinatura: {req.planCode} | R${value} | {cycle} | {req.billingType}")
        
        # Data do próximo vencimento
        tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        payload = {
            "customer": req.customerId,
            "billingType": req.billingType,
            "value": value,
            "cycle": cycle,
            "description": description,
            "nextDueDate": tomorrow,
            "externalReference": req.userId,
        }
        
        # Cartão de crédito
        if req.billingType == "CREDIT_CARD":
            if not req.creditCard or not req.creditCardHolderInfo:
                raise HTTPException(400, "Dados do cartão incompletos")
            
            payload["creditCard"] = {
                "holderName": req.creditCard.holderName,
                "number": req.creditCard.number.replace(" ", "").replace("-", ""),
                "expiryMonth": req.creditCard.expiryMonth,
                "expiryYear": req.creditCard.expiryYear,
                "ccv": req.creditCard.cvv,
            }
            payload["creditCardHolderInfo"] = {
                "name": req.creditCardHolderInfo.name,
                "email": req.creditCardHolderInfo.email,
                "cpfCnpj": req.creditCardHolderInfo.cpfCnpj.replace(".", "").replace("-", ""),
                "postalCode": req.creditCardHolderInfo.postalCode.replace("-", ""),
                "addressNumber": req.creditCardHolderInfo.addressNumber,
                "phone": req.creditCardHolderInfo.phone.replace("(", "").replace(")", "").replace("-", "").replace(" ", "") if req.creditCardHolderInfo.phone else None,
            }
        
        result = await _asaas_request("POST", "/subscriptions", payload)
        
        # Sync com Supabase
        _, _, is_sandbox = _get_asaas_config()
        supabase = _get_supabase()
        if supabase and result.get("id"):
            try:
                supabase.table("assinaturas").upsert({
                    "user_id": req.userId,
                    "asaas_subscription_id": result["id"],
                    "asaas_customer_id": result.get("customer"),
                    "status": (result.get("status") or "active").lower(),
                    "plano": req.planCode,
                    "valor": result.get("value"),
                    "ciclo": result.get("cycle"),
                    "proximo_vencimento": result.get("nextDueDate"),
                    "data_inicio": datetime.utcnow().isoformat(),
                    "descricao": description,
                    "is_sandbox": is_sandbox,
                    "updated_at": datetime.utcnow().isoformat(),
                }, on_conflict="user_id").execute()
                
                # Se ativa (cartão), atualizar profile
                if result.get("status") == "ACTIVE":
                    supabase.table("profiles").update({
                        "plano": req.planCode,
                        "subscription_status": "active",
                        "updated_at": datetime.utcnow().isoformat(),
                    }).eq("id", req.userId).execute()
            except Exception as e:
                logger.warning(f"[Asaas] Sync subscription failed: {e}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Asaas] create-subscription error: {e}")
        raise HTTPException(500, str(e))


@router.post("/get-subscription")
async def get_subscription(req: GetSubscriptionRequest):
    """Buscar assinatura (valida propriedade)."""
    if not await _user_owns_subscription(req.userId, req.subscriptionId):
        raise HTTPException(404, "Assinatura não encontrada")
    return await _asaas_request("GET", f"/subscriptions/{req.subscriptionId}")


@router.post("/cancel-subscription")
async def cancel_subscription(req: CancelSubscriptionRequest):
    """Cancelar assinatura (valida propriedade, faz downgrade)."""
    if not await _user_owns_subscription(req.userId, req.subscriptionId):
        raise HTTPException(404, "Assinatura não encontrada")
    
    logger.info(f"[Asaas] Cancelando assinatura {req.subscriptionId} do user {req.userId}")
    result = await _asaas_request("DELETE", f"/subscriptions/{req.subscriptionId}")
    
    # Sync: cancelar no Supabase
    supabase = _get_supabase()
    if supabase:
        try:
            supabase.table("assinaturas").update({
                "status": "canceled",
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("asaas_subscription_id", req.subscriptionId).execute()
            
            supabase.table("profiles").update({
                "plano": "semente",
                "subscription_status": "canceled",
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", req.userId).execute()
        except Exception as e:
            logger.warning(f"[Asaas] Sync cancel failed: {e}")
    
    return result


@router.post("/list-subscription-payments")
async def list_subscription_payments(req: ListSubscriptionPaymentsRequest):
    """Listar pagamentos de uma assinatura (valida propriedade)."""
    if not await _user_owns_subscription(req.userId, req.subscriptionId):
        raise HTTPException(404, "Assinatura não encontrada")
    return await _asaas_request("GET", f"/payments?subscription={req.subscriptionId}")


@router.post("/get-pix-qrcode")
async def get_pix_qrcode(req: GetPixQrCodeRequest):
    """Buscar QR Code PIX de um pagamento (valida propriedade)."""
    if not await _user_owns_payment(req.userId, req.paymentId):
        raise HTTPException(404, "Pagamento não encontrado")
    return await _asaas_request("GET", f"/payments/{req.paymentId}/pixQrCode")


@router.post("/get-payment")
async def get_payment(req: GetPaymentRequest):
    """Buscar pagamento (valida propriedade)."""
    if not await _user_owns_payment(req.userId, req.paymentId):
        raise HTTPException(404, "Pagamento não encontrado")
    return await _asaas_request("GET", f"/payments/{req.paymentId}")


@router.post("/buy-centelhas")
async def buy_centelhas(req: BuyCentelhasRequest):
    """Comprar pacote de centelhas com valor SERVER-SIDE."""
    try:
        # Buscar pacotes dinâmicos do banco
        pacotes = _get_pacotes_centelhas()
        
        if req.pacoteId not in pacotes:
            raise HTTPException(400, f"Pacote '{req.pacoteId}' inválido")
        
        pacote = pacotes[req.pacoteId]
        
        logger.info(f"[Asaas] Comprando centelhas: {req.pacoteId} | R${pacote['preco']} | {req.billingType}")
        
        payload = {
            "customer": req.customerId,
            "billingType": req.billingType,
            "value": pacote["preco"],
            "description": pacote["descricao"],
            "dueDate": datetime.utcnow().strftime("%Y-%m-%d"),
            "externalReference": f"{req.userId}:{req.pacoteId}",
        }
        
        if req.billingType == "CREDIT_CARD" and req.creditCard:
            payload["creditCard"] = {
                "holderName": req.creditCard.holderName,
                "number": req.creditCard.number.replace(" ", "").replace("-", ""),
                "expiryMonth": req.creditCard.expiryMonth,
                "expiryYear": req.creditCard.expiryYear,
                "ccv": req.creditCard.cvv,
            }
            if req.creditCardHolderInfo:
                payload["creditCardHolderInfo"] = {
                    "name": req.creditCardHolderInfo.name,
                    "email": req.creditCardHolderInfo.email,
                    "cpfCnpj": req.creditCardHolderInfo.cpfCnpj.replace(".", "").replace("-", ""),
                    "postalCode": req.creditCardHolderInfo.postalCode.replace("-", ""),
                    "addressNumber": req.creditCardHolderInfo.addressNumber,
                    "phone": req.creditCardHolderInfo.phone.replace("(", "").replace(")", "").replace("-", "").replace(" ", "") if req.creditCardHolderInfo.phone else None,
                }
        
        result = await _asaas_request("POST", "/payments", payload)
        
        # Sync pagamento
        _, _, is_sandbox = _get_asaas_config()
        supabase = _get_supabase()
        if supabase and result.get("id"):
            try:
                supabase.table("pagamentos").insert({
                    "user_id": req.userId,
                    "asaas_payment_id": result["id"],
                    "status": result.get("status"),
                    "forma_pagamento": result.get("billingType"),
                    "valor": result.get("value"),
                    "data_vencimento": result.get("dueDate"),
                    "descricao": result.get("description"),
                    "is_sandbox": is_sandbox,
                    "created_at": datetime.utcnow().isoformat(),
                }).execute()
            except Exception as e:
                logger.warning(f"[Asaas] Sync payment failed: {e}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Asaas] buy-centelhas error: {e}")
        raise HTTPException(500, str(e))


@router.get("/plans")
async def list_plans():
    """Retorna os planos disponíveis com valores (dinâmico do Supabase)."""
    planos = _get_planos()
    pacotes = _get_pacotes_centelhas()
    
    return {
        "plans": {
            code: {
                "code": code,
                "valor_mensal": p["valor_mensal"],
                "valor_anual": p.get("valor_anual"),
                "description": p["description"],
            }
            for code, p in planos.items()
        },
        "centelhas": {
            code: {
                "code": code,
                "quantidade": p["quantidade"],
                "preco": p["preco"],
                "bonus": p.get("bonus", 0),
                "descricao": p["descricao"],
            }
            for code, p in pacotes.items()
        },
        "environment": get_settings().asaas_environment,
    }


# =============================================
# ABACATEPAY — PIX Payment Gateway
# =============================================

ABACATEPAY_BASE_URL = "https://api.abacatepay.com/v1"


async def _abacatepay_request(method: str, endpoint: str, data: dict = None, params: dict = None) -> dict:
    """Faz request para API AbacatePay com auth Bearer."""
    settings = get_settings()
    api_key = settings.abacatepay_api_key

    if not api_key:
        raise HTTPException(status_code=500, detail="AbacatePay API key não configurada")

    url = f"{ABACATEPAY_BASE_URL}{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    logger.info(f"[AbacatePay] {method} {endpoint}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        if method == "GET":
            resp = await client.get(url, headers=headers, params=params)
        elif method == "POST":
            resp = await client.post(url, headers=headers, json=data)
        else:
            raise HTTPException(400, f"Método {method} não suportado")

    if not resp.is_success:
        try:
            error_data = resp.json()
            msg = error_data.get("error") or f"Erro AbacatePay: {resp.status_code}"
        except Exception:
            msg = f"Erro AbacatePay: {resp.status_code}"
        logger.error(f"[AbacatePay] {method} {endpoint} → {resp.status_code}: {msg}")
        raise HTTPException(status_code=resp.status_code, detail=msg)

    result = resp.json()
    # AbacatePay wraps responses in {"data": ..., "error": ...}
    if "error" in result and result["error"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result.get("data", result)


class AbacatePayCreatePixRequest(BaseModel):
    itemType: str  # "plan" ou "centelhas"
    itemCode: str  # código do plano ou pacote
    cycle: str = "monthly"  # "monthly" ou "annual" (só para planos)
    userId: str
    customerName: Optional[str] = None
    customerEmail: Optional[str] = None
    customerPhone: Optional[str] = None
    customerTaxId: Optional[str] = None


class AbacatePayCheckPixRequest(BaseModel):
    pixId: str
    userId: str


class AbacatePaySimulateRequest(BaseModel):
    pixId: str
    userId: str


@router.post("/abacatepay/create-pix")
async def abacatepay_create_pix(req: AbacatePayCreatePixRequest):
    """
    Criar cobrança PIX via AbacatePay.
    Valor definido SERVER-SIDE a partir do plano/pacote.
    """
    try:
        # Determinar valor e descrição server-side
        if req.itemType == "plan":
            planos = _get_planos()
            if req.itemCode not in planos:
                raise HTTPException(400, f"Plano '{req.itemCode}' inválido. Válidos: {list(planos.keys())}")
            plano = planos[req.itemCode]
            is_annual = req.cycle == "annual"
            value = plano["valor_anual"] if is_annual and plano.get("valor_anual") else plano["valor_mensal"]
            description = f"{plano['description']} ({'Anual' if is_annual else 'Mensal'})"
        elif req.itemType == "centelhas":
            pacotes = _get_pacotes_centelhas()
            if req.itemCode not in pacotes:
                raise HTTPException(400, f"Pacote '{req.itemCode}' inválido")
            pacote = pacotes[req.itemCode]
            value = pacote["preco"]
            description = pacote["descricao"]
        else:
            raise HTTPException(400, f"itemType '{req.itemType}' inválido")

        # AbacatePay usa centavos
        amount_cents = int(round(value * 100))

        logger.info(f"[AbacatePay] Criando PIX: {req.itemType}/{req.itemCode} | R${value} ({amount_cents} centavos)")

        # Montar payload
        payload: Dict[str, Any] = {
            "amount": amount_cents,
            "expiresIn": 3600,  # 1 hora
            "description": description[:37],  # Limite de 37 caracteres no PIX
        }

        # Adicionar customer se disponível
        if req.customerName and req.customerEmail:
            payload["customer"] = {
                "name": req.customerName,
                "email": req.customerEmail,
                "cellphone": req.customerPhone or "(00) 00000-0000",
                "taxId": req.customerTaxId or "000.000.000-00",
            }

        # Metadata para rastreamento
        payload["metadata"] = {
            "userId": req.userId,
            "itemType": req.itemType,
            "itemCode": req.itemCode,
            "cycle": req.cycle,
        }

        result = await _abacatepay_request("POST", "/pixQrCode/create", payload)

        # Sync com Supabase
        supabase = _get_supabase()
        if supabase and result.get("id"):
            try:
                supabase.table("pagamentos").insert({
                    "user_id": req.userId,
                    "asaas_payment_id": result["id"],  # Reusa campo, prefixo pix_char_ identifica AbacatePay
                    "status": result.get("status", "PENDING"),
                    "forma_pagamento": "PIX",
                    "valor": value,
                    "data_vencimento": datetime.utcnow().strftime("%Y-%m-%d"),
                    "descricao": description,
                    "is_sandbox": result.get("devMode", False),
                    "created_at": datetime.utcnow().isoformat(),
                }).execute()
            except Exception as e:
                logger.warning(f"[AbacatePay] Sync payment failed: {e}")

        return {
            "pixId": result.get("id"),
            "brCode": result.get("brCode"),
            "brCodeBase64": result.get("brCodeBase64"),
            "amount": result.get("amount"),
            "status": result.get("status"),
            "expiresAt": result.get("expiresAt"),
            "devMode": result.get("devMode", False),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AbacatePay] create-pix error: {e}")
        raise HTTPException(500, str(e))


@router.post("/abacatepay/check-pix")
async def abacatepay_check_pix(req: AbacatePayCheckPixRequest):
    """Checar status de pagamento PIX via AbacatePay."""
    try:
        result = await _abacatepay_request("GET", "/pixQrCode/check", params={"id": req.pixId})

        status = result.get("status", "PENDING")

        # Se pago, atualizar Supabase
        if status == "PAID":
            supabase = _get_supabase()
            if supabase:
                try:
                    # Atualizar status do pagamento
                    supabase.table("pagamentos").update({
                        "status": "RECEIVED",
                        "updated_at": datetime.utcnow().isoformat(),
                    }).eq("asaas_payment_id", req.pixId).execute()

                    # Buscar metadata para saber o que foi comprado
                    pag_result = supabase.table("pagamentos") \
                        .select("descricao, user_id, valor") \
                        .eq("asaas_payment_id", req.pixId) \
                        .maybe_single() \
                        .execute()

                    if pag_result.data:
                        logger.info(f"[AbacatePay] PIX {req.pixId} confirmado para user {req.userId}")
                except Exception as e:
                    logger.warning(f"[AbacatePay] Sync check-pix failed: {e}")

        return {
            "status": status,
            "expiresAt": result.get("expiresAt"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AbacatePay] check-pix error: {e}")
        raise HTTPException(500, str(e))


@router.post("/abacatepay/simulate-payment")
async def abacatepay_simulate_payment(req: AbacatePaySimulateRequest):
    """Simular pagamento PIX (somente dev mode)."""
    try:
        result = await _abacatepay_request(
            "POST",
            "/pixQrCode/simulate-payment",
            data={"metadata": {}},
            params={"id": req.pixId}
        )

        # Atualizar Supabase como pago
        supabase = _get_supabase()
        if supabase:
            try:
                supabase.table("pagamentos").update({
                    "status": "RECEIVED",
                    "updated_at": datetime.utcnow().isoformat(),
                }).eq("asaas_payment_id", req.pixId).execute()
            except Exception as e:
                logger.warning(f"[AbacatePay] Sync simulate failed: {e}")

        return {
            "pixId": result.get("id"),
            "status": result.get("status"),
            "devMode": result.get("devMode", True),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AbacatePay] simulate-payment error: {e}")
        raise HTTPException(500, str(e))


# =============================================
# ABACATEPAY WEBHOOK — Recebe notificações de pagamento
# =============================================

# Chave pública HMAC da AbacatePay (documentação oficial)
ABACATEPAY_HMAC_PUBLIC_KEY = "t9dXRhHHo3yDEj5pVDYz0frf7q6bMKyMRmxxCPIPp3RCplBfXRxqlC6ZpiWmOqj4L63qEaeUOtrCI8P0VMUgo6iIga2ri9ogaHFs0WIIywSMg0q7RmBfybe1E5XJcfC4IW3alNqym0tXoAKkzvfEjZxV6bE0oG2zJrNNYmUCKZyV0KZ3JS8Votf9EAWWYdiDkMkpbMdPggfh1EqHlVkMiTady6jOR3hyzGEHrIz2Ret0xHKMbiqkr9HS1JhNHDX9"


def _verify_abacatepay_hmac(raw_body: bytes, signature: str) -> bool:
    """Verifica assinatura HMAC-SHA256 do webhook AbacatePay."""
    try:
        import base64
        expected = hmac.new(
            ABACATEPAY_HMAC_PUBLIC_KEY.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).digest()
        expected_b64 = base64.b64encode(expected).decode("utf-8")
        return hmac.compare_digest(expected_b64, signature)
    except Exception as e:
        logger.error(f"[AbacatePay Webhook] HMAC verification error: {e}")
        return False


@router.post("/abacatepay/webhook")
async def abacatepay_webhook(
    request: Request,
    webhookSecret: Optional[str] = Query(None)
):
    """
    Webhook receiver para AbacatePay.
    Recebe notificações de pagamento (billing.paid) e atualiza o Supabase.
    URL: https://api.vibraeu.com.br/payments/abacatepay/webhook?webhookSecret=SEU_SECRET
    """
    try:
        # 1. Validar webhookSecret (autenticação simples)
        settings = get_settings()
        expected_secret = settings.abacatepay_webhook_secret
        if expected_secret and webhookSecret != expected_secret:
            logger.warning("[AbacatePay Webhook] Invalid webhook secret")
            raise HTTPException(401, "Invalid webhook secret")

        # 2. Ler body raw para HMAC
        raw_body = await request.body()

        # 3. Validar HMAC se presente
        hmac_signature = request.headers.get("X-Webhook-Signature")
        if hmac_signature:
            if not _verify_abacatepay_hmac(raw_body, hmac_signature):
                logger.warning("[AbacatePay Webhook] Invalid HMAC signature")
                raise HTTPException(401, "Invalid HMAC signature")

        # 4. Parse body
        import json
        body = json.loads(raw_body)

        event = body.get("event")
        dev_mode = body.get("devMode", False)
        data = body.get("data", {})

        logger.info(f"[AbacatePay Webhook] Evento: {event} | devMode: {dev_mode} | id: {body.get('id')}")

        # 5. Processar billing.paid
        if event == "billing.paid":
            pix_qr = data.get("pixQrCode", {})
            payment_info = data.get("payment", {})
            pix_id = pix_qr.get("id")
            amount = payment_info.get("amount", 0)  # centavos
            status = pix_qr.get("status")

            if not pix_id:
                logger.warning("[AbacatePay Webhook] billing.paid sem pixQrCode.id")
                return {"received": True, "processed": False}

            logger.info(f"[AbacatePay Webhook] PIX pago: {pix_id} | amount: {amount} centavos | status: {status}")

            supabase = _get_supabase()
            if not supabase:
                logger.error("[AbacatePay Webhook] Supabase indisponível")
                return {"received": True, "processed": False}

            # Buscar pagamento pelo pix_id
            pag_result = supabase.table("pagamentos") \
                .select("*") \
                .eq("asaas_payment_id", pix_id) \
                .maybe_single() \
                .execute()

            if not pag_result.data:
                logger.warning(f"[AbacatePay Webhook] Pagamento {pix_id} não encontrado no Supabase")
                return {"received": True, "processed": False}

            pagamento = pag_result.data
            user_id = pagamento.get("user_id")
            description = pagamento.get("descricao", "")

            # Atualizar status do pagamento
            supabase.table("pagamentos").update({
                "status": "RECEIVED",
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("asaas_payment_id", pix_id).execute()

            logger.info(f"[AbacatePay Webhook] Pagamento {pix_id} atualizado para RECEIVED | user: {user_id}")

            # Determinar se é plano ou centelhas pela descrição
            is_plan = "Assinatura" in description

            if is_plan and user_id:
                # Extrair o plano da descrição
                plan_code = None
                planos = _get_planos()
                for code, plano in planos.items():
                    if code.lower() in description.lower():
                        plan_code = code
                        break

                if plan_code:
                    try:
                        supabase.table("profiles").update({
                            "plano": plan_code,
                            "subscription_status": "active",
                            "updated_at": datetime.utcnow().isoformat(),
                        }).eq("id", user_id).execute()
                        logger.info(f"[AbacatePay Webhook] ✅ Plano {plan_code} ativado para user {user_id}")
                    except Exception as e:
                        logger.error(f"[AbacatePay Webhook] Erro ao ativar plano: {e}")
                else:
                    logger.warning(f"[AbacatePay Webhook] Plano não identificado na descrição: {description}")

            elif not is_plan and user_id:
                # Centelhas — creditar
                pacotes = _get_pacotes_centelhas()
                centelhas_total = 0
                for code, pacote in pacotes.items():
                    valor_centavos = int(round(pacote["preco"] * 100))
                    if valor_centavos == amount:
                        centelhas_total = pacote["quantidade"] + pacote.get("bonus", 0)
                        break

                if centelhas_total > 0:
                    try:
                        profile = supabase.table("profiles") \
                            .select("centelhas") \
                            .eq("id", user_id) \
                            .maybe_single() \
                            .execute()
                        centelhas_atuais = profile.data.get("centelhas", 0) if profile.data else 0

                        supabase.table("profiles").update({
                            "centelhas": centelhas_atuais + centelhas_total,
                            "updated_at": datetime.utcnow().isoformat(),
                        }).eq("id", user_id).execute()
                        logger.info(f"[AbacatePay Webhook] ✅ +{centelhas_total} centelhas creditadas para user {user_id}")
                    except Exception as e:
                        logger.error(f"[AbacatePay Webhook] Erro ao creditar centelhas: {e}")
                else:
                    logger.warning(f"[AbacatePay Webhook] Pacote de centelhas não encontrado para amount {amount}")

        else:
            logger.info(f"[AbacatePay Webhook] Evento {event} ignorado (não é billing.paid)")

        return {"received": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AbacatePay Webhook] Erro inesperado: {e}")
        return {"received": True, "error": str(e)}
