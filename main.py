import os
import json
import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

# Configurações de Ambiente
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

PROCESSED_JOBS_FILE = "processed_jobs.json"

# Configuração de Filtro por Região e Perfil
TARGET_LOCATION = "Fortaleza, Ceará, Brasil"  # Altere a região aqui se desejar
PROFILE_TARGET = "Analista (Jr, Pleno, Processos, Projetos, Comercial ou Dados)"
NEGATIVE_KEYWORDS = "Estágio, Presencial fora de Fortaleza/CE, Java, PHP, C++"

# Agrupamos os termos em buscas mais genéricas para economizar requisições HTTP
SEARCH_TERMS = [
    "Analista",
    "Analista de Processos",
    "Analista de Dados"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9"
}

def load_processed_jobs():
    if os.path.exists(PROCESSED_JOBS_FILE):
        try:
            with open(PROCESSED_JOBS_FILE, "r") as f:
                content = f.read().strip()
                return set(json.loads(content)) if content else set()
        except Exception:
            return set()
    return set()

def save_processed_jobs(processed_ids):
    try:
        with open(PROCESSED_JOBS_FILE, "w") as f:
            json.dump(list(processed_ids), f, indent=2)
    except Exception as e:
        print(f"Erro ao salvar histórico: {e}")

# --- SCRAPERS OTIMIZADOS COM FILTRO REGIONAL E TIMEOUT CURTO (5s) ---

def fetch_linkedin_jobs(term):
    # geoId=102061033 ou location ajustada para focar na sua região/remoto
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={term}&location=Fortaleza%2C%20Cear%C3%A1%2C%20Brasil"
    jobs = []
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        for card in soup.find_all("li"):
            title_elem = card.find("h3", class_="base-search-card__title")
            company_elem = card.find("h4", class_="base-search-card__subtitle")
            link_elem = card.find("a", class_="base-card__full-link")
            if title_elem and link_elem:
                href = link_elem["href"].split("?")[0]
                job_id = "linkedin-" + href.split("-")[-1]
                jobs.append({
                    "id": job_id,
                    "title": title_elem.text.strip(),
                    "company": company_elem.text.strip() if company_elem else "Não informado",
                    "link": href,
                    "description": f"Vaga de {title_elem.text.strip()} em {TARGET_LOCATION} ou Remoto",
                    "source": "LinkedIn"
                })
    except Exception as e:
        print(f"Aviso LinkedIn ({term}): {e}")
    return jobs

def fetch_vagas_com_jobs(term):
    formatted_term = term.replace(" ", "-").lower()
    url = f"https://www.vagas.com.br/vagas-de-{formatted_term}-em-fortaleza"
    jobs = []
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        for card in soup.find_all("li", class_="vaga"):
            title_elem = card.find("a", class_="link-detalhes-vaga")
            company_elem = card.find("span", class_="empr")
            if title_elem:
                href = "https://www.vagas.com.br" + title_elem["href"]
                job_id = "vagascom-" + title_elem["href"].split("/")[-2]
                jobs.append({
                    "id": job_id,
                    "title": title_elem.text.strip(),
                    "company": company_elem.text.strip() if company_elem else "Não informado",
                    "link": href,
                    "description": f"Vaga de {title_elem.text.strip()} no Vagas.com (Região {TARGET_LOCATION})",
                    "source": "Vagas.com"
                })
    except Exception as e:
        print(f"Aviso Vagas.com ({term}): {e}")
    return jobs

def fetch_gupy_jobs(term):
    url = f"https://portal.api.gupy.io/api/v1/jobs?jobName={term}&limit=10&offset=0"
    jobs = []
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json()
            for item in data.get("data", []):
                job_id = f"gupy-{item.get('id')}"
                jobs.append({
                    "id": job_id,
                    "title": item.get("name", "Sem título"),
                    "company": item.get("careerPageName", "Empresa na Gupy"),
                    "link": item.get("jobUrl", ""),
                    "description": f"Vaga na Gupy: {item.get('name')}.",
                    "source": "Gupy"
                })
    except Exception as e:
        print(f"Aviso Gupy ({term}): {e}")
    return jobs

# --- FILTRAGEM COM IA REFORÇADA ---

def is_job_relevant_with_ai(job_title, job_description):
    if not GEMINI_API_KEY:
        return True, "Sem API Key"

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = f"""
        Avalie se a vaga é RELEVANTE para o perfil.
        Perfil Desejado: {PROFILE_TARGET}
        Região Preferencial: {TARGET_LOCATION} ou Remoto
        Filtro Negativo: {NEGATIVE_KEYWORDS}

        Vaga: {job_title}
        Descrição: {job_description}

        Responda APENAS em JSON estrito:
        {{"relevant": true, "reason": "motivo curto em ate 6 palavras"}}
        """
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
        )
        text_resp = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text_resp)
        return data.get("relevant", False), data.get("reason", "Aprovado")
    except Exception as e:
        return False, f"Descartado por erro/timeout na IA: {e}"

# --- EXECUÇÃO PRINCIPAL ---

def send_telegram(job, reason):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    msg = f"🎯 <b>Nova Vaga ({job['source']})!</b>\n\n📌 <b>Cargo:</b> {job['title']}\n🏢 <b>Empresa:</b> {job['company']}\n💡 <b>IA:</b> {reason}\n\n🔗 <a href='{job['link']}'>Ver Vaga</a>"
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=5
        )
    except Exception:
        pass

def main():
    processed = load_processed_jobs()
    all_jobs = []

    for term in SEARCH_TERMS:
        all_jobs.extend(fetch_linkedin_jobs(term))
        all_jobs.extend(fetch_vagas_com_jobs(term))
        all_jobs.extend(fetch_gupy_jobs(term))

    print(f"Total de vagas encontradas: {len(all_jobs)}")

    for job in all_jobs:
        if job["id"] in processed:
            continue

        relevant, reason = is_job_relevant_with_ai(job["title"], job["description"])
        if relevant:
            print(f"[APROVADA] {job['title']} - {job['source']}")
            send_telegram(job, reason)

        processed.add(job["id"])

    save_processed_jobs(processed)
    print("Execução rápida concluída com sucesso!")

if __name__ == "__main__":
    main()
