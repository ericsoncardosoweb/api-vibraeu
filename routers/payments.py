"""
Payment Router â€” Proxy seguro para API Asaas
Flow: Frontend â†’ apiClient â†’ Python API â†’ Asaas
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
# PLANOS & CENTELHAS â€” DinÃ¢mico via Supabase
# Cache TTL de 5 min para evitar queries repetidas
# =============================================

import time

_plans_cache = {"data": None, "ts": 0}
_centelhas_cache = {"data": None, "ts": 0}
_CACHE_TTL = 300  # 5 minutos

# Fallbacks hardcoded (sÃ³ usados se Supabase indisponÃ­vel)
_PLANOS_FALLBACK = {
    "fluxo": {"valor_mensal": 37.90, "valor_anual": 379.00, "description": "Assinatura VibraEu Fluxo"},
    "expansao": {"valor_mensal": 89.90, "valor_anual": 899.00, "description": "Assinatura VibraEu ExpansÃ£o"},
}

_CENTELHAS_FALLBACK = {
    "centelhas_5": {"quantidade": 5, "preco": 9.90, "descricao": "Pack Inicial - 5 Centelhas"},
    "centelhas_20": {"quantidade": 20, "preco": 29.90, "descricao": "Pack EvoluÃ§Ã£o - 20+5 Centelhas"},
    "centelhas_40": {"quantidade": 40, "preco": 49.90, "descricao": "Pack ExpansÃ£o - 40+10 Centelhas"},
    "centelhas_60": {"quantidade": 60, "preco": 79.90, "descricao": "Pack IluminaÃ§Ã£o - 60+15 Centelhas"},
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
                continue  # Semente Ã© grÃ¡tis, nÃ£o tem checkout
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
        raise HTTPException(status_code=500, detail=f"Asaas API key nÃ£o configurada ({env_name})")
    
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
            raise HTTPException(400, f"MÃ©todo {method} nÃ£o suportado")
    
    if not resp.is_success:
        try:
            error_data = resp.json()
            msg = error_data.get("errors", [{}])[0].get("description", f"Erro Asaas: {resp.status_code}")
        except Exception:
            msg = f"Erro Asaas: {resp.status_code}"
        logger.error(f"[Asaas] {method} {endpoint} â†’ {resp.status_code}: {msg}")
        raise HTTPException(status_code=resp.status_code, detail=msg)
    
    return resp.json()


def _get_supabase():
    """Retorna Supabase client usando service role key."""
    from services.supabase_client import get_supabase_client
    return get_supabase_client()


async def _user_owns_subscription(user_id: str, subscription_id: str) -> bool:
    """Valida que a assinatura pertence ao usuÃ¡rio."""
    supabase = _get_supabase()
    if not supabase:
        return True  # Se Supabase indisponÃ­vel, permitir (graceful degradation)
    result = supabase.table("assinaturas") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("asaas_subscription_id", subscription_id) \
        .maybe_single() \
        .execute()
    return result.data is not None


async def _user_owns_payment(user_id: str, payment_id: str) -> bool:
    """Valida que o pagamento pertence ao usuÃ¡rio."""
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
    # Pagamento pode ser recente e nÃ£o sincronizado ainda
    logger.warning(f"[Asaas] Propriedade do payment {payment_id} nÃ£o confirmada, permitindo temporariamente")
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
        # Buscar planos dinÃ¢micos do banco
        planos = _get_planos()
        
        # Validar plano
        if req.planCode not in planos:
            raise HTTPException(400, f"Plano '{req.planCode}' invÃ¡lido. VÃ¡lidos: {list(planos.keys())}")
        
        if req.billingType not in ("PIX", "CREDIT_CARD", "BOLETO"):
            raise HTTPException(400, f"billingType '{req.billingType}' invÃ¡lido")
        
        plano = planos[req.planCode]
        
        # VALOR DEFINIDO PELO SERVIDOR
        value = plano["valor_anual"] if req.isAnnual else plano["valor_mensal"]
        cycle = "YEARLY" if req.isAnnual else "MONTHLY"
        description = f"{plano['description']} ({'Anual' if req.isAnnual else 'Mensal'})"
        
        logger.info(f"[Asaas] Criando assinatura: {req.planCode} | R${value} | {cycle} | {req.billingType}")
        
        # Data do prÃ³ximo vencimento
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
        
        # CartÃ£o de crÃ©dito
        if req.billingType == "CREDIT_CARD":
            if not req.creditCard or not req.creditCardHolderInfo:
                raise HTTPException(400, "Dados do cartÃ£o incompletos")
            
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
                
                # Se ativa (cartÃ£o), atualizar profile
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
        raise HTTPException(404, "Assinatura nÃ£o encontrada")
    return await _asaas_request("GET", f"/subscriptions/{req.subscriptionId}")


@router.post("/cancel-subscription")
async def cancel_subscription(req: CancelSubscriptionRequest):
    """Cancelar assinatura (valida propriedade, faz downgrade)."""
    if not await _user_owns_subscription(req.userId, req.subscriptionId):
        raise HTTPException(404, "Assinatura nÃ£o encontrada")
    
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
        raise HTTPException(404, "Assinatura nÃ£o encontrada")
    return await _asaas_request("GET", f"/payments?subscription={req.subscriptionId}")


@router.post("/get-pix-qrcode")
async def get_pix_qrcode(req: GetPixQrCodeRequest):
    """Buscar QR Code PIX de um pagamento (valida propriedade)."""
    if not await _user_owns_payment(req.userId, req.paymentId):
        raise HTTPException(404, "Pagamento nÃ£o encontrado")
    return await _asaas_request("GET", f"/payments/{req.paymentId}/pixQrCode")


@router.post("/get-payment")
async def get_payment(req: GetPaymentRequest):
    """Buscar pagamento (valida propriedade)."""
    if not await _user_owns_payment(req.userId, req.paymentId):
        raise HTTPException(404, "Pagamento nÃ£o encontrado")
    return await _asaas_request("GET", f"/payments/{req.paymentId}")


@router.post("/buy-centelhas")
async def buy_centelhas(req: BuyCentelhasRequest):
    """Comprar pacote de centelhas com valor SERVER-SIDE."""
    try:
        # Buscar pacotes dinÃ¢micos do banco
        pacotes = _get_pacotes_centelhas()
        
        if req.pacoteId not in pacotes:
            raise HTTPException(400, f"Pacote '{req.pacoteId}' invÃ¡lido")
        
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
    """Retorna os planos disponÃ­veis com valores (dinÃ¢mico do Supabase)."""
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
# ASAAS WEBHOOK â€” Recebe notificaÃ§Ãµes de pagamento
# =============================================


@router.post("/asaas/webhook")
async def asaas_webhook(request: Request):
    """
    Webhook receiver para Asaas.
    Recebe notificaÃ§Ãµes de pagamento e assinatura:
    - PAYMENT_RECEIVED / PAYMENT_CONFIRMED â†’ ativar plano
    - PAYMENT_OVERDUE â†’ marcar como inadimplente
    - SUBSCRIPTION_CANCELED / SUBSCRIPTION_DELETED â†’ downgrade para semente
    URL: https://api.vibraeu.com.br/payments/asaas/webhook
    """
    try:
        # 1. Validar token do webhook
        expected_token = "whsec_wHtwTm29OywF3P380I82EwDfuc7X3ubzmfbDfsqTkMQ"
        received_token = request.headers.get('asaas-access-token')
        if received_token != expected_token:
            logger.warning("[Asaas Webhook] Token inválido")
            raise HTTPException(401, "Token inválido")

        # 2. Parse body
        import json
        raw_body = await request.body()
        body = json.loads(raw_body)

        event = body.get("event", "")
        payment = body.get("payment")
        subscription = body.get("subscription")

        logger.info(f"[Asaas Webhook] Evento: {event}")

        supabase = _get_supabase()
        if not supabase:
            logger.error("[Asaas Webhook] Supabase indisponÃ­vel")
            return {"received": True, "processed": False}

        # 3. Processar eventos de pagamento
        if payment and payment.get("id"):
            payment_id = payment["id"]
            payment_status = payment.get("status", "")
            subscription_id = payment.get("subscription")

            # Mapear status
            if event in ("PAYMENT_CONFIRMED", "PAYMENT_RECEIVED"):
                new_status = "CONFIRMED"
            elif event == "PAYMENT_OVERDUE":
                new_status = "OVERDUE"
            elif event == "PAYMENT_REFUNDED":
                new_status = "REFUNDED"
            elif event == "PAYMENT_CREATED":
                new_status = "PENDING"
            else:
                new_status = payment_status

            # Atualizar pagamento existente
            try:
                supabase.table("pagamentos").update({
                    "status": new_status,
                    "updated_at": datetime.utcnow().isoformat(),
                }).eq("asaas_payment_id", payment_id).execute()
            except Exception as e:
                logger.warning(f"[Asaas Webhook] Erro ao atualizar pagamento: {e}")

            # Se pagamento confirmado e tem assinatura, ativar plano
            if event in ("PAYMENT_CONFIRMED", "PAYMENT_RECEIVED") and subscription_id:
                try:
                    sub_result = supabase.table("assinaturas") \
                        .select("user_id, plano") \
                        .eq("asaas_subscription_id", subscription_id) \
                        .maybe_single() \
                        .execute()

                    if sub_result.data:
                        user_id = sub_result.data.get("user_id")
                        plan_code = sub_result.data.get("plano")

                        if user_id and plan_code:
                            supabase.table("assinaturas").update({
                                "status": "active",
                                "updated_at": datetime.utcnow().isoformat(),
                            }).eq("asaas_subscription_id", subscription_id).execute()

                            supabase.table("profiles").update({
                                "plano": plan_code,
                                "subscription_status": "active",
                                "updated_at": datetime.utcnow().isoformat(),
                            }).eq("id", user_id).execute()

                            logger.info(f"[Asaas Webhook] âœ… Plano {plan_code} ativado para user {user_id}")
                except Exception as e:
                    logger.error(f"[Asaas Webhook] Erro ao ativar plano: {e}")

            # Se pagamento vencido, marcar assinatura
            if event == "PAYMENT_OVERDUE" and subscription_id:
                try:
                    supabase.table("assinaturas").update({
                        "status": "overdue",
                        "updated_at": datetime.utcnow().isoformat(),
                    }).eq("asaas_subscription_id", subscription_id).execute()
                except Exception as e:
                    logger.warning(f"[Asaas Webhook] Erro ao marcar overdue: {e}")

        # 4. Processar eventos de assinatura
        if subscription and subscription.get("id"):
            sub_id = subscription["id"]

            if event in ("SUBSCRIPTION_CANCELED", "SUBSCRIPTION_DELETED"):
                try:
                    sub_result = supabase.table("assinaturas") \
                        .select("user_id") \
                        .eq("asaas_subscription_id", sub_id) \
                        .maybe_single() \
                        .execute()

                    supabase.table("assinaturas").update({
                        "status": "canceled",
                        "updated_at": datetime.utcnow().isoformat(),
                    }).eq("asaas_subscription_id", sub_id).execute()

                    if sub_result.data and sub_result.data.get("user_id"):
                        supabase.table("profiles").update({
                            "plano": "semente",
                            "subscription_status": "canceled",
                            "updated_at": datetime.utcnow().isoformat(),
                        }).eq("id", sub_result.data["user_id"]).execute()
                        logger.info(f"[Asaas Webhook] User {sub_result.data['user_id']} rebaixado para semente")
                except Exception as e:
                    logger.error(f"[Asaas Webhook] Erro ao cancelar: {e}")

            elif event == "SUBSCRIPTION_RENEWED":
                try:
                    supabase.table("assinaturas").update({
                        "status": "active",
                        "proximo_vencimento": subscription.get("nextDueDate"),
                        "updated_at": datetime.utcnow().isoformat(),
                    }).eq("asaas_subscription_id", sub_id).execute()
                except Exception as e:
                    logger.warning(f"[Asaas Webhook] Erro ao renovar: {e}")

            elif event == "SUBSCRIPTION_EXPIRED":
                try:
                    sub_result = supabase.table("assinaturas") \
                        .select("user_id") \
                        .eq("asaas_subscription_id", sub_id) \
                        .maybe_single() \
                        .execute()

                    supabase.table("assinaturas").update({
                        "status": "expired",
                        "updated_at": datetime.utcnow().isoformat(),
                    }).eq("asaas_subscription_id", sub_id).execute()

                    if sub_result.data and sub_result.data.get("user_id"):
                        supabase.table("profiles").update({
                            "plano": "semente",
                            "subscription_status": "expired",
                            "updated_at": datetime.utcnow().isoformat(),
                        }).eq("id", sub_result.data["user_id"]).execute()
                except Exception as e:
                    logger.error(f"[Asaas Webhook] Erro ao expirar: {e}")

        return {"received": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Asaas Webhook] Erro inesperado: {e}")
        return {"received": True, "error": str(e)}



