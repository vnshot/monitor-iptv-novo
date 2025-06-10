import streamlit as st
import requests
import time
from datetime import datetime
import pandas as pd
import threading
import telebot
from urllib.parse import urlparse
from secrets2 import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, SERVIDOR_URLS
import pytz
import io
import socket
import platform
import json
from datetime import timezone

# Função para mascarar URL
# Agora retorna sempre apenas "Oculto"
def mask_url(url):
    return "Oculto"

# Inicialização do bot com retry
def init_telegram_bot():
    for attempt in range(3):
        try:
            bot = telebot.TeleBot(TELEGRAM_TOKEN)
            bot.get_me()
            return bot
        except Exception as e:
            if attempt == 2:
                st.warning("⚠️ Não foi possível conectar ao Telegram. O monitoramento continuará, mas sem notificações.")
                return None
            time.sleep(2)

# Função para enviar mensagem no Telegram com retry
def send_telegram_message(message, bot):
    if bot is None:
        return
        
    for attempt in range(3):
        try:
            bot.send_message(TELEGRAM_CHAT_ID, message, parse_mode='HTML')
            return
        except Exception as e:
            if attempt == 2:
                st.error(f"❌ Erro ao enviar mensagem para o Telegram (tentativa {attempt + 1}/3)")
            else:
                time.sleep(2)
                continue

# Função para verificar uma única URL com retentativas
def check_single_url(url, servidor_nome, bot):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "*/*"
    }
    
    last_status = st.session_state.get(f"last_status_{servidor_nome}", None)
    start_time = time.time()
    
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=30, stream=True)
            response_time = time.time() - start_time
            
            try:
                next(response.iter_content(chunk_size=1024))
                if last_status == "offline":
                    send_telegram_message(f"✅ Servidor <b>{servidor_nome}</b> está ONLINE novamente!", bot)
                st.session_state[f"last_status_{servidor_nome}"] = "online"
                st.session_state[f"response_time_{servidor_nome}"] = response_time
                return "🟢 Online", response_time
            except:
                if last_status != "offline":
                    send_telegram_message(f"❌ Servidor <b>{servidor_nome}</b> está OFFLINE!\nErro: Sem conteúdo", bot)
                st.session_state[f"last_status_{servidor_nome}"] = "offline"
                return f"🔴 Offline (Sem conteúdo)", None
                
        except requests.RequestException as e:
            if attempt == 2:
                error_msg = str(e)
                if last_status != "offline":
                    send_telegram_message(f"❌ Servidor <b>{servidor_nome}</b> está OFFLINE!\nErro: {error_msg}", bot)
                st.session_state[f"last_status_{servidor_nome}"] = "offline"
                
                if "timeout" in error_msg.lower():
                    return f"🔴 Offline (Timeout)", None
                elif "dns" in error_msg.lower():
                    return f"🔴 Offline (DNS)", None
                else:
                    return f"🔴 Offline ({error_msg})", None
            time.sleep(1)
    
    return "❓ Status Desconhecido", None

def ping_host(host, timeout=1):
    """Retorna a latência em ms ou None se não for possível pingar."""
    try:
        if platform.system().lower() == "windows":
            from subprocess import check_output
            output = check_output(["ping", "-n", "1", "-w", str(timeout*1000), host]).decode()
            if "tempo=" in output:
                return int(output.split("tempo=")[1].split("ms")[0].strip())
        else:
            from subprocess import check_output
            output = check_output(["ping", "-c", "1", "-W", str(timeout), host]).decode()
            if "time=" in output:
                return int(float(output.split("time=")[1].split(" ms")[0].strip()))
    except Exception:
        return None

# Lista de servidores para monitorar
servidores = [{"nome": nome, "url": url} for nome, url in SERVIDOR_URLS.items()]

# Configuração da página
st.set_page_config(page_title="Monitor IPTV", page_icon="📺", layout="wide")

# Configurar tema escuro/claro
if 'theme' not in st.session_state:
    st.session_state.theme = "dark"

# Inicializar bot do Telegram
bot = init_telegram_bot()

# Sidebar para configurações
with st.sidebar:
    st.title("⚙️ Configurações")
    
    if st.button("🌓 Alternar Tema"):
        st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
    
    st.subheader("📢 Notificações")
    notification_types = st.multiselect(
        "Tipos de Notificação",
        ["🔴 Servidor Offline", "✅ Servidor Online", "📊 Relatório Diário"],
        default=["🔴 Servidor Offline", "✅ Servidor Online"]
    )
    
    st.subheader("📈 Histórico")
    show_history = st.checkbox("Mostrar Gráfico de Uptime", value=True)
    
    st.subheader("🔍 Filtros")
    status_filter = st.multiselect(
        "Status",
        ["Online", "Offline"],
        default=["Online", "Offline"]
    )

# Título principal
st.title("📺 Monitor de Servidores IPTV")

# Função para verificar URLs
# Corrigir timezone para GMT-3 (America/Sao_Paulo) usando pytz
TZ = pytz.timezone('America/Sao_Paulo')
def check_urls(bot):
    results = []
    for servidor in servidores:
        status, response_time = check_single_url(servidor["url"], servidor["nome"], bot)
        # Teste de latência (ping)
        try:
            host = servidor["url"].split("//")[-1].split("/")[0]
            latency = ping_host(host)
        except Exception:
            latency = None
        results.append({
            "Nome": servidor["nome"],
            "URL": mask_url(servidor["url"]),
            "Status": status,
            "Tempo de Resposta": f"{response_time:.2f}s" if response_time else "N/A",
            "Latência (Ping)": f"{latency} ms" if latency is not None else "N/A",
            "Última Verificação": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "Detalhes": status if "Offline" in status else ""
        })
    return pd.DataFrame(results)

# Inicializar ou atualizar dados
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = datetime.now(TZ)
    st.session_state.df = check_urls(bot)

# Controles de atualização
col_refresh, col_auto = st.columns([1, 2])

with col_refresh:
    if st.button("🔄 Atualizar Agora"):
        st.session_state.last_refresh = datetime.now(TZ)
        st.session_state.df = check_urls(bot)

with col_auto:
    auto_refresh = st.checkbox("Atualização Automática", value=True)
    refresh_interval = st.slider("Intervalo de Atualização (segundos)", 
                               min_value=30, max_value=300, value=60)

# Mostrar última atualização
st.caption(f"Última atualização: {st.session_state.last_refresh.strftime('%Y-%m-%d %H:%M:%S')}")

# --- Persistência do Histórico em JSON ---
def save_history():
    try:
        with open('historico_uptime.json', 'w', encoding='utf-8') as f:
            json.dump([
                {'timestamp': h['timestamp'].strftime('%Y-%m-%d %H:%M:%S'), 'status': h['status']}
                for h in st.session_state.history
            ], f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"Erro ao salvar histórico: {e}")

def load_history():
    try:
        with open('historico_uptime.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Converte timestamp para datetime com timezone correto
        return [
            {'timestamp': datetime.strptime(h['timestamp'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TZ), 'status': h['status']}
            for h in data
        ]
    except Exception:
        return []

# Carregar histórico persistente ao iniciar
if 'history' not in st.session_state:
    st.session_state.history = load_history()

# Gerenciar histórico
current_status = {
    'timestamp': datetime.now(TZ),
    'status': {servidor['nome']: 'Online' in st.session_state.df[st.session_state.df['Nome'] == servidor['nome']]['Status'].iloc[0] 
               for servidor in servidores}
}
st.session_state.history.append(current_status)
# Limitar histórico a 24 horas
one_day_ago = datetime.now(TZ) - pd.Timedelta(days=1)
st.session_state.history = [h for h in st.session_state.history if h['timestamp'] > one_day_ago]
save_history()

# --- Relatório diário automático (envia às 23:59) ---
now = datetime.now(TZ)
if now.hour == 23 and now.minute == 59 and 'last_daily_report' not in st.session_state:
    send_daily_report(bot)
    st.session_state['last_daily_report'] = now.date()
if 'last_daily_report' in st.session_state and st.session_state['last_daily_report'] != now.date():
    del st.session_state['last_daily_report']

# Função para enviar relatório diário automático no Telegram
# (precisa estar definida antes do uso)
def send_daily_report(bot):
    if bot is None:
        return
    try:
        with open('historico_uptime.json', 'r', encoding='utf-8') as f:
            history = json.load(f)
    except Exception:
        history = []
    if not history:
        return
    total = len(history)
    if total == 0:
        return
    servidores = list(history[-1]['status'].keys())
    online_counts = {s: 0 for s in servidores}
    for h in history:
        for s in servidores:
            if h['status'].get(s):
                online_counts[s] += 1
    uptime_percent = {s: (online_counts[s]/total)*100 for s in servidores}
    incidentes = {s: total-online_counts[s] for s in servidores}
    msg = '<b>📊 Relatório Diário IPTV</b>\n'
    for s in servidores:
        msg += f"\n<b>{s}</b>: Uptime: {uptime_percent[s]:.1f}% | Incidentes: {incidentes[s]}"
    send_telegram_message(msg, bot)

# --- Exibir Última Mensagem de Erro ---
# Salva última mensagem de erro para cada servidor
if 'last_error' not in st.session_state:
    st.session_state.last_error = {}
for servidor in servidores:
    nome = servidor['nome']
    status_row = st.session_state.df[st.session_state.df['Nome'] == nome]
    if not status_row.empty and 'Offline' in status_row['Status'].iloc[0]:
        st.session_state.last_error[nome] = status_row['Status'].iloc[0]

# --- Dashboard Resumido ---
# Calcula métricas principais antes do dashboard
total_servers = len(servidores)
online_servers = len([x for x in st.session_state.df["Status"] if "Online" in x])
offline_servers = total_servers - online_servers
uptime_24h = 0
avg_response = 0
if len(st.session_state.history) > 0:
    # Uptime nas últimas 24h (proporção de servidores online em cada registro)
    total_registros = len([h for h in st.session_state.history if h['timestamp'] > one_day_ago])
    if total_registros > 0:
        uptime_24h = sum(
            sum(1 for v in h['status'].values() if v) / len(h['status'])
            for h in st.session_state.history if h['timestamp'] > one_day_ago
        ) / total_registros * 100
    else:
        uptime_24h = 0
    # Tempo médio de resposta
    valid_responses = [
        float(getattr(r, 'Tempo_de_Resposta', getattr(r, 'Tempo de Resposta', 'N/A')).replace('s',''))
        for r in st.session_state.df.itertuples()
        if getattr(r, 'Tempo_de_Resposta', getattr(r, 'Tempo de Resposta', 'N/A')) != 'N/A'
    ]
    avg_response = sum(valid_responses) / len(valid_responses) if valid_responses else 0

# Dashboard
st.markdown("""
<div style='display: flex; gap: 2rem; margin-bottom: 1.5rem;'>
  <div style='background: #222; color: #fff; padding: 1rem; border-radius: 8px; min-width: 160px;'>
    <b>Servidores:</b><br> <span style='font-size: 1.5em;'>{}</span>
  </div>
  <div style='background: #222; color: #fff; padding: 1rem; border-radius: 8px; min-width: 160px;'>
    <b>Online:</b><br> <span style='font-size: 1.5em;'>{}</span>
  </div>
  <div style='background: #222; color: #fff; padding: 1rem; border-radius: 8px; min-width: 160px;'>
    <b>Offline:</b><br> <span style='font-size: 1.5em;'>{}</span>
  </div>
  <div style='background: #222; color: #fff; padding: 1rem; border-radius: 8px; min-width: 160px;'>
    <b>Uptime 24h:</b><br> <span style='font-size: 1.5em;'>{:.1f}%</span>
  </div>
  <div style='background: #222; color: #fff; padding: 1rem; border-radius: 8px; min-width: 160px;'>
    <b>Tempo Médio:</b><br> <span style='font-size: 1.5em;'>{}</span>
  </div>
</div>
""".format(total_servers, online_servers, offline_servers, uptime_24h if len(st.session_state.history) > 0 else 0, avg_response), unsafe_allow_html=True)

# Gráfico de Uptime
if show_history and st.session_state.history:
    st.subheader("📈 Uptime nas Últimas 24h")
    history_df = pd.DataFrame([
        {'timestamp': h['timestamp'], 'servidor': k, 'status': v}
        for h in st.session_state.history
        for k, v in h['status'].items()
    ])
    uptime_df = history_df.groupby('servidor')['status'].mean().reset_index()
    uptime_df['uptime'] = (uptime_df['status'] * 100).round(2)
    st.bar_chart(uptime_df.set_index('servidor')['uptime'])
    # Gráfico de tendência do tempo de resposta
    st.subheader("📉 Tendência do Tempo de Resposta (últimas 24h)")
    if 'df' in st.session_state:
        trend_df = st.session_state.df[['Nome', 'Tempo de Resposta']].copy()
        trend_df['Tempo de Resposta'] = trend_df['Tempo de Resposta'].apply(lambda x: float(x.replace('s','')) if x != 'N/A' else None)
        st.line_chart(trend_df.set_index('Nome')['Tempo de Resposta'])

# Tabela de Status
st.subheader("🖥️ Status dos Servidores")
filtered_df = st.session_state.df.copy()
if status_filter:
    filtered_df = filtered_df[filtered_df['Status'].apply(lambda x: any(status in x for status in status_filter))]

# Adiciona coluna de detalhes do erro (hover)
filtered_df["Detalhes"] = filtered_df["Status"].apply(lambda x: x if "Offline" in x else "")

# Atualiza tabela para mostrar latência
filtered_df["Último Erro"] = filtered_df["Nome"].apply(lambda n: st.session_state.last_error.get(n, ""))

st.dataframe(
    filtered_df,
    column_config={
        "Nome": st.column_config.TextColumn("Nome", width="medium"),
        "URL": st.column_config.TextColumn("URL (Credenciais Ocultas)", width="large"),
        "Status": st.column_config.TextColumn("Status", width="medium"),
        "Tempo de Resposta": st.column_config.TextColumn("Tempo de Resposta", width="medium"),
        "Latência (Ping)": st.column_config.TextColumn("Latência (Ping)", width="medium"),
        "Última Verificação": st.column_config.TextColumn("Última Verificação", width="medium"),
        "Detalhes": st.column_config.TextColumn("Detalhes do Erro", width="large"),
        "Último Erro": st.column_config.TextColumn("Último Erro", width="large"),
    },
    hide_index=True,
    use_container_width=True
)

# --- Autenticação simples por senha ---
PASSWORD = "iptv2024"  # Troque para uma senha forte
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if not st.session_state.authenticated:
    st.title("🔒 Monitor IPTV - Login")
    pwd = st.text_input("Digite a senha para acessar:", type="password")
    if st.button("Entrar"):
        if pwd == PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Senha incorreta!")
    st.stop()

# --- Dica de uso mobile ---
st.info("💡 Dica: Para melhor experiência em dispositivos móveis, use o navegador na horizontal.")

# --- Adição/remoção de servidores via interface (temporário) ---
with st.sidebar:
    st.subheader("📝 Gerenciar Servidores (sessão)")
    if 'custom_servers' not in st.session_state:
        st.session_state.custom_servers = []
    novo_nome = st.text_input("Nome do novo servidor")
    novo_url = st.text_input("URL do novo servidor")
    if st.button("Adicionar Servidor") and novo_nome and novo_url:
        st.session_state.custom_servers.append({"nome": novo_nome, "url": novo_url})
        st.success(f"Servidor '{novo_nome}' adicionado!")
    if st.session_state.custom_servers:
        remove_nome = st.selectbox("Remover servidor", [s['nome'] for s in st.session_state.custom_servers])
        if st.button("Remover Selecionado"):
            st.session_state.custom_servers = [s for s in st.session_state.custom_servers if s['nome'] != remove_nome]
            st.success(f"Servidor '{remove_nome}' removido!")

# --- Atualiza lista de servidores ---
servidores = [{"nome": nome, "url": url} for nome, url in SERVIDOR_URLS.items()]
servidores += st.session_state.get('custom_servers', [])

# Atualizar dados com servidores personalizados
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = datetime.now(TZ)
    st.session_state.df = check_urls(bot)

# Atualização automática
if auto_refresh and (datetime.now(TZ) - st.session_state.last_refresh).seconds >= refresh_interval:
    st.session_state.df = check_urls(bot)
    st.session_state.last_refresh = datetime.now(TZ)
    st.rerun()

# Mensagem inicial do Telegram
if 'telegram_initialized' not in st.session_state and bot is not None:
    try:
        send_telegram_message("✅ Monitor IPTV iniciado e conectado ao Telegram!", bot)
        st.session_state.telegram_initialized = True
        st.success("✅ Bot do Telegram conectado com sucesso!")
    except Exception as e:
        st.warning("⚠️ Monitor iniciado, mas não foi possível enviar mensagem no Telegram.")
