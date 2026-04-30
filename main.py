import os
import time
import sqlite3
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES E CAMINHOS ---
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(DIRETORIO_ATUAL, '.env'))
CAMINHO_BANCO = os.path.join(DIRETORIO_ATUAL, 'vagas_gupy.db')

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID_GRUPO")

TRADUCAO_MODELO = {
    "on-site": "Presencial",
    "hybrid": "Híbrido",
    "remote": "Remoto"
}

TRADUCAO_TIPO_VAGA = {
    "vacancy_type_effective": "Efetivo",
    "vacancy_type_apprentice": "Jovem Aprendiz",
    "vacancy_type_internship": "Estágio",
    "vacancy_type_temporary": "Temporário",
    "vacancy_type_freelancer": "Freelancer"
}

# --- 2. BANCO DE DADOS ---
def iniciar_banco():
    conn = sqlite3.connect(CAMINHO_BANCO)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vagas_enviadas (
            link TEXT PRIMARY KEY,
            data_publicacao TEXT,
            titulo TEXT
        )
    ''')
    conn.commit()
    return conn, cursor

# --- 3. MOTOR DE BUSCA DA GUPY (RJ + REMOTO) ---
def buscar_vagas_gupy():
    print("🚀 Iniciando varredura detalhada na API da Gupy...")
    conn, cursor = iniciar_banco()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://portal.gupy.io'
    }
    
    url_api = "https://employability-portal.gupy.io/api/v1/jobs"
    
    filtros_de_busca = [
        {"nome": "BELO HORIZONTE", "params": {'state': 'Minas Gerais', 'city': 'Belo Horizonte', 'limit': 10}},
        {"nome": "HOME OFFICE", "params": {'workplaceTypes': 'remote', 'limit': 10}}
    ]

    for filtro in filtros_de_busca:
        print(f"\n🔎 Varrendo vagas para: {filtro['nome']}...")
        
        vagas_velhas = 0
        LIMITE_VELHAS = 20
        PAGINA_MAXIMA = 35  # Ajuste aqui! (10 páginas = 100 vagas varridas por busca)
        
        # ⚠️ NOVO SISTEMA: Navegação por páginas
        for pagina in range(1, PAGINA_MAXIMA + 1):
            print(f"   ⏳ Lendo página {pagina} de {PAGINA_MAXIMA}...")
            
            offset = (pagina - 1) * 10
            
            params_atuais = filtro['params'].copy()
            params_atuais['offset'] = offset
            
            try:
                resposta = requests.get(url_api, headers=headers, params=params_atuais, timeout=15)
                
                if resposta.status_code != 200: 
                    print(f"🛑 Erro de conexão. Código HTTP: {resposta.status_code}")
                    break
                
                try:
                    dados_json = resposta.json()
                except Exception:
                    print(f"🛑 Fomos bloqueados! O servidor não enviou os dados JSON.")
                    break

                lista_vagas = dados_json.get('data', [])
                if not lista_vagas: 
                    print("   🔚 Não há mais vagas disponíveis nesta busca.")
                    break # Fim das páginas no servidor da Gupy

                for vaga in lista_vagas:
                    link_vaga = vaga.get('jobUrl', '')
                    if not link_vaga: continue
                    
                    titulo = vaga.get('name', 'Título Indisponível')
                    empresa = vaga.get('careerPageName', 'Empresa não informada')
                    
                    if filtro['nome'] == "HOME OFFICE":
                        local = "Qualquer lugar (Remoto)"
                    else:
                        local = f"{vaga.get('city', 'RJ')} - {vaga.get('state', 'RJ')}"
                    
                    modelo = TRADUCAO_MODELO.get(vaga.get('workplaceType', ''), "Não informado")
                    tipo = TRADUCAO_TIPO_VAGA.get(vaga.get('type', ''), "Outros")
                    pcd = "Sim" if vaga.get('disabilities') else "Não informado"

                    data_iso = vaga.get('publishedDate', '')
                    try:
                        data_limpa = data_iso.split('.')[0] 
                        data_utc = datetime.strptime(data_limpa, "%Y-%m-%dT%H:%M:%S")
                        data_brt = data_utc - timedelta(hours=3)
                        data_f = data_brt.strftime("%d/%m/%Y")
                        hora_f = data_brt.strftime("%H:%M")
                    except Exception:
                        data_f, hora_f = "Sem data", "--:--"

                    cursor.execute('SELECT 1 FROM vagas_enviadas WHERE link = ?', (link_vaga,))
                    if cursor.fetchone():
                        vagas_velhas += 1
                        if vagas_velhas >= LIMITE_VELHAS: 
                            break # Para o loop dessa página específica
                    else:
                        vagas_velhas = 0 
                        cursor.execute('INSERT INTO vagas_enviadas VALUES (?, ?, ?)', (link_vaga, data_f, titulo))
                        conn.commit()
                        
                        titulo_mensagem = f"🎯 <b>VAGA GUPY - {filtro['nome']}!</b>"
                        mensagem = f"{titulo_mensagem}\n\n" \
                                   f"💼 <b>Vaga:</b> {titulo}\n" \
                                   f"🏢 <b>Empresa:</b> {empresa}\n" \
                                   f"📍 <b>Local:</b> {local}\n" \
                                   f"💻 <b>Modelo:</b> {modelo}\n" \
                                   f"📄 <b>Tipo:</b> {tipo}\n" \
                                   f"♿ <b>PCD:</b> {pcd}\n" \
                                   f"📅 <b>Data:</b> {data_f} às {hora_f}\n\n" \
                                   f"🔗 <a href='{link_vaga}'>Clique aqui para aplicar na Gupy</a>"

                        url_tg = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                        payload_tg = {"chat_id": CHAT_ID, "text": mensagem, "parse_mode": "HTML", "disable_web_page_preview": True}
                        
                        try:
                            r = requests.post(url_tg, json=payload_tg, timeout=10)
                            if r.status_code == 200:
                                print(f"✅ Enviada ({filtro['nome']}): {titulo[:40]}...")
                        except Exception as e:
                            print(f"❌ Erro ao enviar para o Telegram: {e}")
                        
                        time.sleep(2)
                
                # Checa se o limite bateu para abortar as próximas páginas
                if vagas_velhas >= LIMITE_VELHAS:
                    print(f"   🛑 Muitas vagas antigas ({LIMITE_VELHAS}). Pulando para a próxima busca.")
                    break 

            except Exception as e:
                print(f"⚠️ Erro de execução: {e}")
                break

    conn.close()
    print("\n✅ Varredura dupla finalizada!")

if __name__ == '__main__':
    if not TOKEN or not CHAT_ID:
        print("❌ ERRO: Token do Telegram ou Chat ID não encontrados no arquivo .env!")
    else:
        buscar_vagas_gupy()
