"""
Monthly Reports Service — Geração de relatórios mensais via IA.
Relatórios: Diário de Bordo e Metas/Hábitos.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from loguru import logger
import json

from services.supabase_client import get_supabase_client
from services.llm_gateway import LLMGateway


def get_mes_referencia(mes: Optional[str] = None) -> str:
    """Retorna mês de referência no formato YYYY-MM."""
    if mes:
        return mes
    now = datetime.utcnow()
    return now.strftime("%Y-%m")


# ============================================================================
# Coleta de dados — Diário de Bordo
# ============================================================================

async def coletar_dados_diario(user_id: str, mes_referencia: str) -> Dict[str, Any]:
    """
    Coleta e processa todas as entradas do diário do mês.
    Retorna dados estruturados para o prompt.
    """
    supabase = get_supabase_client()
    
    # Calcular range de datas do mês
    year, month = map(int, mes_referencia.split("-"))
    start_date = f"{mes_referencia}-01"
    if month == 12:
        end_date = f"{year + 1}-01-01"
    else:
        end_date = f"{year}-{month + 1:02d}-01"
    
    # Buscar entradas do mês
    response = supabase.table("daily_entries") \
        .select("*") \
        .eq("user_id", user_id) \
        .gte("entry_date", start_date) \
        .lt("entry_date", end_date) \
        .order("entry_date", desc=False) \
        .execute()
    
    entries = response.data or []
    
    if not entries:
        return {"total_entries": 0, "entries": []}
    
    # Processar estatísticas
    moods = [e["mood"] for e in entries if e.get("mood")]
    avg_mood = round(sum(moods) / len(moods), 2) if moods else 0
    
    # Distribuição de mood labels
    mood_distribution = {}
    for e in entries:
        label = e.get("mood_label", "Desconhecido")
        mood_distribution[label] = mood_distribution.get(label, 0) + 1
    
    # Contagem de emoções
    emotion_counts = {}
    for e in entries:
        for emotion in (e.get("emotions") or []):
            emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1
    
    # Top emoções ordenadas
    top_emotions = sorted(
        [{"label": k, "count": v} for k, v in emotion_counts.items()],
        key=lambda x: x["count"],
        reverse=True
    )[:15]
    
    # Classificar emoções por categoria
    POSITIVE_EMOTIONS = {
        "Alegre", "Esperançoso", "Maravilhado", "Aliviado", "Confiante",
        "Contente", "Satisfeito", "Feliz", "Apaixonado", "Entusiasmado",
        "Animado", "Corajoso", "Orgulhoso", "Calmo", "Curioso", "Grato",
        "Tranquilo", "Relaxado"
    }
    NEGATIVE_EMOTIONS = {
        "Triste", "Com raiva", "Irritado", "Ansioso", "Assustado",
        "Com nojo", "Ciumento", "Culpado", "Envergonhado", "Decepcionado",
        "Estressado", "Desesperançoso", "Solitário", "Cansado", "Deprimido"
    }
    
    positive_count = sum(v for k, v in emotion_counts.items() if k in POSITIVE_EMOTIONS)
    negative_count = sum(v for k, v in emotion_counts.items() if k in NEGATIVE_EMOTIONS)
    neutral_count = sum(v for k, v in emotion_counts.items() if k not in POSITIVE_EMOTIONS and k not in NEGATIVE_EMOTIONS)
    total_emotions = positive_count + negative_count + neutral_count
    
    emotion_balance = {
        "positive": round(positive_count / total_emotions * 100) if total_emotions > 0 else 0,
        "negative": round(negative_count / total_emotions * 100) if total_emotions > 0 else 0,
        "neutral": round(neutral_count / total_emotions * 100) if total_emotions > 0 else 0
    }
    
    # Contagem de fatores
    factor_counts = {}
    for e in entries:
        for factor in (e.get("factors") or []):
            factor_counts[factor] = factor_counts.get(factor, 0) + 1
    
    top_factors = sorted(
        [{"label": k, "count": v} for k, v in factor_counts.items()],
        key=lambda x: x["count"],
        reverse=True
    )[:10]
    
    # Distribuição por dia da semana
    weekday_names = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    weekday_mood = {d: [] for d in weekday_names}
    for e in entries:
        try:
            date = datetime.strptime(e["entry_date"], "%Y-%m-%d")
            day_name = weekday_names[date.weekday()]
            if e.get("mood"):
                weekday_mood[day_name].append(e["mood"])
        except (ValueError, KeyError):
            pass
    
    weekday_avg = {
        day: round(sum(moods_list) / len(moods_list), 1) if moods_list else None
        for day, moods_list in weekday_mood.items()
    }
    
    # Notas/reflexões do mês (resumidas)
    notes_entries = [
        {"date": e["entry_date"], "mood": e.get("mood"), "mood_label": e.get("mood_label"), "notes": e.get("notes", "")[:500]}
        for e in entries if e.get("notes")
    ]
    
    return {
        "total_entries": len(entries),
        "dias_no_mes": (datetime(year, month + 1 if month < 12 else 1, 1, tzinfo=None) - datetime(year, month, 1, tzinfo=None)).days,
        "avg_mood": avg_mood,
        "mood_distribution": mood_distribution,
        "top_emotions": top_emotions,
        "emotion_balance": emotion_balance,
        "top_factors": top_factors,
        "weekday_avg_mood": weekday_avg,
        "notes_resumo": notes_entries[:20],  # Máximo 20 notas para o prompt
        "entries_raw": [
            {
                "date": e["entry_date"],
                "mood": e.get("mood"),
                "mood_label": e.get("mood_label"),
                "emotions": e.get("emotions", []),
                "factors": e.get("factors", [])
            }
            for e in entries
        ]
    }


# ============================================================================
# Coleta de dados — Metas & Hábitos
# ============================================================================

CATEGORIAS_RODA = {
    1: "Saúde Física", 2: "Saúde Mental", 3: "Finanças", 4: "Carreira",
    5: "Relacionamentos", 6: "Família", 7: "Espiritualidade", 8: "Lazer",
    9: "Crescimento", 10: "Contribuição", 11: "Ambiente", 12: "Criatividade"
}

async def coletar_dados_metas(user_id: str, mes_referencia: str) -> Dict[str, Any]:
    """
    Coleta e processa dados de metas e hábitos do mês.
    Retorna dados estruturados para o prompt.
    """
    supabase = get_supabase_client()
    
    # Calcular range de datas
    year, month = map(int, mes_referencia.split("-"))
    start_date = f"{mes_referencia}-01"
    if month == 12:
        end_date = f"{year + 1}-01-01"
    else:
        end_date = f"{year}-{month + 1:02d}-01"
    
    # Buscar TODAS as metas do usuário (ativas + completadas no mês)
    goals_response = supabase.table("goals") \
        .select("*") \
        .eq("user_id", user_id) \
        .execute()
    
    all_goals = goals_response.data or []
    
    if not all_goals:
        return {"total_goals": 0}
    
    # Separar por tipo
    habitos = [g for g in all_goals if g.get("goal_type") == "habit"]
    projetos = [g for g in all_goals if g.get("goal_type") != "habit"]
    
    # Metas ativas
    habitos_ativos = [h for h in habitos if h.get("status") == "active"]
    projetos_ativos = [p for p in projetos if p.get("status") == "active"]
    
    # Metas completadas no mês
    projetos_concluidos = [
        p for p in projetos
        if p.get("status") == "completed" and p.get("completed_at")
        and p["completed_at"][:7] == mes_referencia
    ]
    
    # Buscar logs de progresso do mês
    logs_response = supabase.table("goal_logs") \
        .select("*") \
        .gte("log_date", start_date) \
        .lt("log_date", end_date) \
        .execute()
    
    all_logs = logs_response.data or []
    # Filtrar logs que pertencem a metas do usuário
    goal_ids = {g["id"] for g in all_goals}
    user_logs = [l for l in all_logs if l.get("goal_id") in goal_ids]
    
    # Calcular progresso por meta
    def calc_progress(goal):
        if goal.get("target_value") and goal["target_value"] > 0:
            return min(100, round((goal.get("current_value", 0) / goal["target_value"]) * 100))
        return goal.get("progress", 0)
    
    # Estatísticas de hábitos
    habitos_data = []
    for h in habitos_ativos:
        habitos_data.append({
            "title": h.get("title"),
            "category": CATEGORIAS_RODA.get(h.get("category_id"), "Sem categoria"),
            "category_id": h.get("category_id"),
            "current_streak": h.get("current_streak", 0),
            "best_streak": h.get("best_streak", 0),
            "frequency": h.get("habit_frequency", "daily"),
            "days": h.get("habit_days", []),
            "created_at": h.get("created_at", "")[:10]
        })
    
    # Estatísticas de projetos
    projetos_data = []
    for p in projetos_ativos + projetos_concluidos:
        progress = calc_progress(p)
        projetos_data.append({
            "title": p.get("title"),
            "category": CATEGORIAS_RODA.get(p.get("category_id"), "Sem categoria"),
            "category_id": p.get("category_id"),
            "status": p.get("status"),
            "progress": progress,
            "start_value": p.get("start_value", 0),
            "current_value": p.get("current_value", 0),
            "target_value": p.get("target_value", 0),
            "unit": p.get("unit", ""),
            "deadline": p.get("deadline"),
            "importance": p.get("importance_reason"),
            "created_at": p.get("created_at", "")[:10]
        })
    
    # Áreas cobertas vs negligenciadas
    areas_com_metas = set()
    for g in habitos_ativos + projetos_ativos:
        if g.get("category_id"):
            areas_com_metas.add(g["category_id"])
    
    areas_negligenciadas = [
        {"id": k, "area": v}
        for k, v in CATEGORIAS_RODA.items()
        if k not in areas_com_metas
    ]
    
    # Streaks
    streaks = [h.get("current_streak", 0) for h in habitos_ativos]
    avg_streak = round(sum(streaks) / len(streaks), 1) if streaks else 0
    max_streak = max(streaks) if streaks else 0
    
    # Progresso médio dos projetos
    progresses = [calc_progress(p) for p in projetos_ativos]
    avg_progress = round(sum(progresses) / len(progresses)) if progresses else 0
    
    # Metas abandonadas/canceladas no mês (auto-sabotagem)
    abandonadas = [
        {"title": g.get("title"), "category": CATEGORIAS_RODA.get(g.get("category_id"), ""), "status": g.get("status")}
        for g in all_goals
        if g.get("status") in ("cancelled", "archived")
        and g.get("updated_at", "")[:7] == mes_referencia
    ]
    
    # Logs de progresso (atividade do mês)
    logs_por_meta = {}
    for l in user_logs:
        gid = l.get("goal_id")
        if gid not in logs_por_meta:
            logs_por_meta[gid] = []
        logs_por_meta[gid].append({
            "date": l.get("log_date"),
            "previous": l.get("previous_value"),
            "new": l.get("new_value"),
            "description": l.get("description", "")[:200]
        })
    
    total_logs = len(user_logs)
    
    return {
        "total_habitos_ativos": len(habitos_ativos),
        "total_projetos_ativos": len(projetos_ativos),
        "total_projetos_concluidos": len(projetos_concluidos),
        "total_abandonadas": len(abandonadas),
        "habitos": habitos_data,
        "projetos": projetos_data,
        "areas_negligenciadas": areas_negligenciadas,
        "total_areas_cobertas": len(areas_com_metas),
        "avg_streak": avg_streak,
        "max_streak": max_streak,
        "avg_progress_projetos": avg_progress,
        "total_logs_mes": total_logs,
        "abandonadas": abandonadas,
        "conquistas": [
            {"title": p.get("title"), "category": CATEGORIAS_RODA.get(p.get("category_id"), "")}
            for p in projetos_concluidos
        ]
    }


# ============================================================================
# Buscar perfil do usuário
# ============================================================================

async def buscar_perfil_usuario(user_id: str) -> Dict[str, Any]:
    """Busca perfil do usuário para personalização do prompt."""
    supabase = get_supabase_client()
    
    try:
        response = supabase.table("profiles") \
            .select("nome, sexo, profissao, data_nascimento, estado_civil, tem_filhos") \
            .eq("id", user_id) \
            .single() \
            .execute()
        
        return response.data or {}
    except Exception as e:
        logger.warning(f"[MonthlyReports] Erro ao buscar perfil: {e}")
        return {}


# ============================================================================
# Prompts de geração
# ============================================================================

SYSTEM_PROMPT_DIARIO = """Você é Luna, a mentora de autoconhecimento do app Vibra EU.
Sua missão neste relatório é analisar o mês emocional do usuário com profundidade, empatia e inteligência.

REGRAS IMPORTANTES:
1. Seja direta, reveladora e amorosa. Nada de frases genéricas.
2. Use os DADOS REAIS — frequências, padrões, correlações. O usuário quer se ENXERGAR nos dados.
3. Identifique PADRÕES: dias da semana com queda, emoções recorrentes, fatores que disparam estados negativos.
4. Confronte com gentileza: se há inconsistências (diz estar bem mas registra emoções negativas), aponte.
5. Linguagem de 2ª pessoa (você), tom caloroso e não-julgamental.
6. Use emojis estratégicos (✨🌙💫) sem exagero.
7. HTML formatado com <h3> para subtítulos, <p> para parágrafos, <strong> para ênfase, <ul>/<li> para listas.

ESTRUTURA DO RELATÓRIO:
- Resumo do mês (como foi a jornada emocional)
- Padrões identificados (dias da semana, gatilhos, ciclos)
- Emoções predominantes e o que revelam
- Fatores que mais influenciaram o humor
- Pontos de atenção (áreas que precisam de cuidado)
- Lições e aprendizados do mês
- Desafios que você enfrentou

Retorne ESTRITAMENTE um JSON com as chaves:
- "report_html": String HTML do relatório completo
- "patterns_identified": Array de strings com padrões encontrados
- "relevance_score": Nota de 0 a 10 indicando quão rico e relevante foi este mês de dados emocionais (0=vazio, 10=mês muito rico em padrões)
- "frase_final": Uma frase poderosa que resuma a essência emocional do mês"""

SYSTEM_PROMPT_METAS = """Você é Luna, a mentora de autoconhecimento do app Vibra EU.
Sua missão neste relatório é analisar o progresso e compromisso do usuário com suas metas e hábitos.

REGRAS IMPORTANTES:
1. Diferencie PROJETOS (objetivos de médio/longo prazo como comprar casa, faculdade) de HÁBITOS (práticas diárias).
2. Use os DADOS REAIS — taxas de progresso, streaks, abandonos. O usuário quer clareza sobre suas ações.
3. Identifique PADRÕES DE AUTO-SABOTAGEM: hábitos abandonados, metas estagnadas, áreas negligenciadas.
4. Celebre conquistas genuínas — não invente méritos.
5. Correlacione com as 12 áreas da Roda da Vida: quais estão sendo nutridas e quais esquecidas?
6. Seja direta sobre auto-sabotagem mas com compaixão — ajude a pessoa a ENXERGAR o que está fazendo.
7. Linguagem de 2ª pessoa (você), tom caloroso e empoderador.
8. Use emojis estratégicos (🎯✨💪) sem exagero.
9. HTML formatado com <h3> para subtítulos, <p> para parágrafos, <strong> para ênfase, <ul>/<li> para listas.

ESTRUTURA DO RELATÓRIO:
- Visão geral (total de metas, hábitos ativos, taxa de engajamento)
- Conquistas do mês (projetos concluídos, streaks mantidos)
- Hábitos: consistência e comprometimento real
- Projetos: progresso real vs expectativa
- Auto-sabotagem detectada (se houver)
- Áreas negligenciadas da Roda da Vida
- Recomendações práticas para o próximo mês

Retorne ESTRITAMENTE um JSON com as chaves:
- "report_html": String HTML do relatório completo
- "taxa_realizacao": Número de 0-100 representando taxa geral de compromisso
- "relevance_score": Nota de 0 a 10 indicando quão rico e relevante foi este mês em termos de ação e progresso (0=inativo, 10=mês muito ativo)
- "frase_final": Uma frase poderosa que resuma a relação do usuário com suas metas"""


# ============================================================================
# Geração de relatórios
# ============================================================================

async def gerar_relatorio_diario(user_id: str, mes_referencia: Optional[str] = None) -> Dict[str, Any]:
    """
    Gera relatório mensal do Diário de Bordo.
    Coleta dados, envia para LLM, salva resultado e cria notificação.
    """
    mes = get_mes_referencia(mes_referencia)
    supabase = get_supabase_client()
    
    logger.info(f"[MonthlyReports] Gerando relatório DIÁRIO para {user_id} - {mes}")
    
    # Verificar/criar registro pendente
    try:
        existing = supabase.table("monthly_reports") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("report_type", "diario") \
            .eq("mes_referencia", mes) \
            .execute()
        
        if existing.data and existing.data[0].get("status") == "available":
            logger.info(f"[MonthlyReports] Relatório diário já existe para {mes}")
            return {"success": True, "data": existing.data[0], "already_exists": True}
    except Exception:
        pass
    
    # Criar/atualizar registro como generating
    try:
        supabase.table("monthly_reports").upsert({
            "user_id": user_id,
            "report_type": "diario",
            "mes_referencia": mes,
            "status": "generating"
        }, on_conflict="user_id,report_type,mes_referencia").execute()
    except Exception as e:
        logger.error(f"[MonthlyReports] Erro ao criar registro: {e}")
    
    try:
        # Coletar dados
        dados = await coletar_dados_diario(user_id, mes)
        
        if dados["total_entries"] < 3:
            # Atualizar como erro
            supabase.table("monthly_reports").update({
                "status": "error",
                "error_message": f"Registros insuficientes ({dados['total_entries']}/3 mínimo)"
            }).eq("user_id", user_id).eq("report_type", "diario").eq("mes_referencia", mes).execute()
            
            return {"success": False, "error": f"Registros insuficientes ({dados['total_entries']}/3 mínimo)"}
        
        # Buscar perfil
        perfil = await buscar_perfil_usuario(user_id)
        
        # Montar prompt
        mes_nome = datetime.strptime(f"{mes}-01", "%Y-%m-%d").strftime("%B/%Y")
        prompt = f"""Analise o mês emocional deste usuário e gere o relatório mensal.

**Mês:** {mes_nome}
**Perfil:** {json.dumps(perfil, ensure_ascii=False)}

**DADOS DO MÊS:**
- Total de registros: {dados['total_entries']} de {dados['dias_no_mes']} dias
- Média de humor: {dados['avg_mood']}/5
- Distribuição de humor: {json.dumps(dados['mood_distribution'], ensure_ascii=False)}
- Balanço emocional: {json.dumps(dados['emotion_balance'], ensure_ascii=False)}
- Top emoções: {json.dumps(dados['top_emotions'][:10], ensure_ascii=False)}
- Top fatores: {json.dumps(dados['top_factors'][:8], ensure_ascii=False)}
- Humor por dia da semana: {json.dumps(dados['weekday_avg_mood'], ensure_ascii=False)}

**REGISTROS DETALHADOS (dia a dia):**
{json.dumps(dados['entries_raw'], ensure_ascii=False)}

**REFLEXÕES ESCRITAS:**
{json.dumps(dados['notes_resumo'], ensure_ascii=False)}

Gere um relatório profundo e revelador. Retorne APENAS o JSON."""

        # Chamar LLM
        gateway = LLMGateway.get_instance()
        raw_response = await gateway.generate(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT_DIARIO,
            config={
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "fallback_provider": "groq",
                "fallback_model": "llama-3.3-70b-versatile",
                "temperature": 0.7,
                "max_tokens": 4000
            }
        )
        
        # Parsear resposta
        report_data = _parse_llm_json(raw_response)
        
        # Enriquecer com dados estatísticos
        report_data.update({
            "total_entries": dados["total_entries"],
            "avg_mood": dados["avg_mood"],
            "mood_distribution": dados["mood_distribution"],
            "top_emotions": dados["top_emotions"][:10],
            "top_factors": dados["top_factors"][:8],
            "emotion_balance": dados["emotion_balance"]
        })
        
        # Salvar resultado
        result = supabase.table("monthly_reports").update({
            "status": "available",
            "report_data": report_data,
            "input_summary": {
                "total_entries": dados["total_entries"],
                "avg_mood": dados["avg_mood"],
                "dias_no_mes": dados["dias_no_mes"]
            },
            "error_message": None
        }).eq("user_id", user_id).eq("report_type", "diario").eq("mes_referencia", mes).execute()
        
        # Criar notificação
        await _criar_notificacao(
            user_id,
            title="📊 Relatório Mensal do Diário de Bordo",
            message=f"Seu relatório de {mes_nome} está pronto! A Luna analisou seus registros e identificou padrões importantes.",
            link="/diario",
            icon="fa-book-open",
            icon_color="#9933CC"
        )
        
        logger.info(f"[MonthlyReports] ✅ Relatório DIÁRIO gerado com sucesso para {user_id}")
        return {"success": True, "data": result.data[0] if result.data else report_data}
        
    except Exception as e:
        logger.error(f"[MonthlyReports] ❌ Erro ao gerar relatório diário: {e}")
        
        # Atualizar como erro
        try:
            supabase.table("monthly_reports").update({
                "status": "error",
                "error_message": str(e)[:500]
            }).eq("user_id", user_id).eq("report_type", "diario").eq("mes_referencia", mes).execute()
        except Exception:
            pass
        
        return {"success": False, "error": str(e)}


async def gerar_relatorio_metas(user_id: str, mes_referencia: Optional[str] = None) -> Dict[str, Any]:
    """
    Gera relatório mensal de Metas & Hábitos.
    Coleta dados, envia para LLM, salva resultado e cria notificação.
    """
    mes = get_mes_referencia(mes_referencia)
    supabase = get_supabase_client()
    
    logger.info(f"[MonthlyReports] Gerando relatório METAS para {user_id} - {mes}")
    
    # Verificar/criar registro
    try:
        existing = supabase.table("monthly_reports") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("report_type", "metas") \
            .eq("mes_referencia", mes) \
            .execute()
        
        if existing.data and existing.data[0].get("status") == "available":
            logger.info(f"[MonthlyReports] Relatório metas já existe para {mes}")
            return {"success": True, "data": existing.data[0], "already_exists": True}
    except Exception:
        pass
    
    # Criar/atualizar registro como generating
    try:
        supabase.table("monthly_reports").upsert({
            "user_id": user_id,
            "report_type": "metas",
            "mes_referencia": mes,
            "status": "generating"
        }, on_conflict="user_id,report_type,mes_referencia").execute()
    except Exception as e:
        logger.error(f"[MonthlyReports] Erro ao criar registro: {e}")
    
    try:
        # Coletar dados
        dados = await coletar_dados_metas(user_id, mes)
        
        total = dados.get("total_habitos_ativos", 0) + dados.get("total_projetos_ativos", 0)
        if total == 0:
            supabase.table("monthly_reports").update({
                "status": "error",
                "error_message": "Nenhuma meta ou hábito encontrado"
            }).eq("user_id", user_id).eq("report_type", "metas").eq("mes_referencia", mes).execute()
            
            return {"success": False, "error": "Nenhuma meta ou hábito encontrado"}
        
        # Buscar perfil
        perfil = await buscar_perfil_usuario(user_id)
        
        # Montar prompt
        mes_nome = datetime.strptime(f"{mes}-01", "%Y-%m-%d").strftime("%B/%Y")
        prompt = f"""Analise o progresso de metas e hábitos deste usuário e gere o relatório mensal.

**Mês:** {mes_nome}
**Perfil:** {json.dumps(perfil, ensure_ascii=False)}

**VISÃO GERAL:**
- Hábitos ativos: {dados['total_habitos_ativos']}
- Projetos ativos: {dados['total_projetos_ativos']}
- Projetos concluídos no mês: {dados['total_projetos_concluidos']}
- Metas abandonadas/canceladas: {dados['total_abandonadas']}
- Áreas da Roda da Vida cobertas: {dados['total_areas_cobertas']}/12
- Logs de progresso registrados: {dados['total_logs_mes']}
- Streak médio dos hábitos: {dados['avg_streak']} dias
- Streak máximo: {dados['max_streak']} dias
- Progresso médio dos projetos: {dados['avg_progress_projetos']}%

**HÁBITOS ATIVOS (práticas diárias):**
{json.dumps(dados.get('habitos', []), ensure_ascii=False)}

**PROJETOS (médio/longo prazo):**
{json.dumps(dados.get('projetos', []), ensure_ascii=False)}

**CONQUISTAS DO MÊS:**
{json.dumps(dados.get('conquistas', []), ensure_ascii=False)}

**METAS ABANDONADAS (auto-sabotagem?):**
{json.dumps(dados.get('abandonadas', []), ensure_ascii=False)}

**ÁREAS NEGLIGENCIADAS DA RODA DA VIDA:**
{json.dumps(dados.get('areas_negligenciadas', []), ensure_ascii=False)}

Gere um relatório profundo e revelador. Retorne APENAS o JSON."""

        # Chamar LLM
        gateway = LLMGateway.get_instance()
        raw_response = await gateway.generate(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT_METAS,
            config={
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "fallback_provider": "groq",
                "fallback_model": "llama-3.3-70b-versatile",
                "temperature": 0.7,
                "max_tokens": 4000
            }
        )
        
        # Parsear resposta
        report_data = _parse_llm_json(raw_response)
        
        # Enriquecer com dados estatísticos
        report_data.update({
            "total_habitos_ativos": dados["total_habitos_ativos"],
            "total_projetos_ativos": dados["total_projetos_ativos"],
            "total_projetos_concluidos": dados["total_projetos_concluidos"],
            "avg_streak": dados["avg_streak"],
            "max_streak": dados["max_streak"],
            "avg_progress_projetos": dados["avg_progress_projetos"],
            "areas_negligenciadas": dados["areas_negligenciadas"],
            "conquistas": dados.get("conquistas", []),
            "abandonadas": dados.get("abandonadas", [])
        })
        
        # Salvar resultado
        result = supabase.table("monthly_reports").update({
            "status": "available",
            "report_data": report_data,
            "input_summary": {
                "total_habitos": dados["total_habitos_ativos"],
                "total_projetos": dados["total_projetos_ativos"],
                "total_logs": dados["total_logs_mes"]
            },
            "error_message": None
        }).eq("user_id", user_id).eq("report_type", "metas").eq("mes_referencia", mes).execute()
        
        # Criar notificação
        await _criar_notificacao(
            user_id,
            title="🎯 Relatório Mensal de Metas e Hábitos",
            message=f"Seu relatório de {mes_nome} está pronto! A Luna analisou seu progresso e compromisso com suas metas.",
            link="/metas",
            icon="fa-bullseye",
            icon_color="#00CCD6"
        )
        
        logger.info(f"[MonthlyReports] ✅ Relatório METAS gerado com sucesso para {user_id}")
        return {"success": True, "data": result.data[0] if result.data else report_data}
        
    except Exception as e:
        logger.error(f"[MonthlyReports] ❌ Erro ao gerar relatório metas: {e}")
        
        try:
            supabase.table("monthly_reports").update({
                "status": "error",
                "error_message": str(e)[:500]
            }).eq("user_id", user_id).eq("report_type", "metas").eq("mes_referencia", mes).execute()
        except Exception:
            pass
        
        return {"success": False, "error": str(e)}


# ============================================================================
# Utilitários
# ============================================================================

def _parse_llm_json(raw: str) -> Dict[str, Any]:
    """Parseia a resposta do LLM removendo markdown e extraindo JSON."""
    text = raw.strip()
    
    # Remover blocos de código markdown
    if "```json" in text:
        text = text.split("```json", 1)[1]
        if "```" in text:
            text = text.split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1]
        if "```" in text:
            text = text.split("```", 1)[0]
    
    text = text.strip()
    
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"[MonthlyReports] Não foi possível parsear JSON, usando como HTML")
        return {"report_html": raw, "frase_final": ""}


async def _criar_notificacao(
    user_id: str,
    title: str,
    message: str,
    link: str = None,
    icon: str = "fa-chart-bar",
    icon_color: str = "#9933CC"
):
    """Cria notificação no Supabase para o usuário."""
    supabase = get_supabase_client()
    
    try:
        supabase.table("notifications").insert({
            "user_id": user_id,
            "type": "star",
            "icon": icon,
            "icon_color": icon_color,
            "title": title,
            "message": message,
            "link": link,
            "is_read": False
        }).execute()
        
        logger.info(f"[MonthlyReports] 🔔 Notificação criada para {user_id}: {title}")
    except Exception as e:
        logger.error(f"[MonthlyReports] Erro ao criar notificação: {e}")
