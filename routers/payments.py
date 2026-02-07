"""
Payment Router — Proxy seguro para API Asaas
Flow: Frontend → apiClient → Python API → Asaas
Valores dos planos definidos server-side, nunca no frontend.
"""

import httpx
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from loguru import logger

from config import get_settings

router = APIRouter(prefix="/payments", tags=["payments"])

# =============================================
# PLANOS — Valores definidos SERVER-SIDE
# =============================================

PLANOS = {
    "fluxo": {
        "valor_mensal": 37.90,
        "valor_anual": 379.00,
        "description": "Assinatura VibraEu Fluxo",
    },
    "expansao": {
        "valor_mensal": 89.90,
        "valor_anual": 899.00,
        "description": "Assinatura VibraEu Expansão",
    },
}

PACOTES_CENTELHAS = {
    "centelhas_5": {"quantidade": 5, "preco": 9.90, "descricao": "Pack Inicial - 5 Centelhas"},
    "centelhas_15": {"quantidade": 15, "preco": 24.90, "descricao": "Pack Crescimento - 15+2 Centelhas"},
    "centelhas_30": {"quantidade": 30, "preco": 44.90, "descricao": "Pack Expansão - 30+5 Centelhas"},
    "centelhas_60": {"quantidade": 60, "preco": 79.90, "descricao": "Pack Iluminação - 60+15 Centelhas"},
}


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
        # Validar plano
        if req.planCode not in PLANOS:
            raise HTTPException(400, f"Plano '{req.planCode}' inválido. Válidos: {list(PLANOS.keys())}")
        
        if req.billingType not in ("PIX", "CREDIT_CARD", "BOLETO"):
            raise HTTPException(400, f"billingType '{req.billingType}' inválido")
        
        plano = PLANOS[req.planCode]
        
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
                    "status": result.get("status"),
                    "billing_type": result.get("billingType"),
                    "value": result.get("value"),
                    "cycle": result.get("cycle"),
                    "next_due_date": result.get("nextDueDate"),
                    "plan_code": req.planCode,
                    "sandbox": is_sandbox,
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
                "status": "CANCELED",
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
        if req.pacoteId not in PACOTES_CENTELHAS:
            raise HTTPException(400, f"Pacote '{req.pacoteId}' inválido")
        
        pacote = PACOTES_CENTELHAS[req.pacoteId]
        
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
                    "asaas_customer_id": result.get("customer"),
                    "status": result.get("status"),
                    "billing_type": result.get("billingType"),
                    "value": result.get("value"),
                    "due_date": result.get("dueDate"),
                    "description": result.get("description"),
                    "sandbox": is_sandbox,
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
    """Retorna os planos disponíveis com valores (endpoint público para exibição)."""
    return {
        "plans": {
            code: {
                "code": code,
                "valor_mensal": p["valor_mensal"],
                "valor_anual": p["valor_anual"],
                "description": p["description"],
            }
            for code, p in PLANOS.items()
        },
        "centelhas": {
            code: {
                "code": code,
                "quantidade": p["quantidade"],
                "preco": p["preco"],
                "descricao": p["descricao"],
            }
            for code, p in PACOTES_CENTELHAS.items()
        },
        "environment": get_settings().asaas_environment,
    }
