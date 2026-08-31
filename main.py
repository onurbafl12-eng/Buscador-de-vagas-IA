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

# Perfil Desejado e Exclusões para a IA
PROFILE_TARGET = "Analista de Dados, Engenheiro de Dados ou Especialista em Automação Python"
NEGATIVE_KEYWORDS = "Estágio, Vaga Presencial com mais de 50km, Java, PHP, C++"

def load_processed_jobs():
    if os.path.exists(PROCESSED_JOBS_FILE):
        try:
            with open(PROCESSED_JOBS_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_processed_jobs(processed_ids):
    with open(PROCESSED_JOBS_FILE, "w") as f:
        json.dump(list(processed_ids), f, indent=2)

# --- SCRAPERS PARA PLATAFORMAS REAIS ---

def fetch_linkedin_jobs(term="Analista de Dados"):
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={term}&location=Brasil"
    headers = {"User-Agent": "Mozilla/5.0"}
    jobs = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        for card in soup.find_all("li"):
            title_elem = card.find("h3", class_="base-search-card__title")
            company_elem = card.find("h4", class_="base-search-card__subtitle")
            link_elem = card.find("a", class_="base-card__full-link")
            if title_elem and link_elem:
                job_id = "linkedin-" + link_elem["href"].split("?")[0].split("-")[-1]
                jobs.append({
                    "id": job_id,
                    "title": title_elem.text.strip(),
                    "company": company_elem.text.strip() if company_elem else "Não informado",
                    "link": link_elem["href"].split("?")[0],
                    "description": f"Vaga de {title_elem.text.strip()} no LinkedIn",
                    "source": "LinkedIn"
                })
    except Exception as e:
        print(f"Erro LinkedIn: {e}")
    return jobs

def fetch_vagas_com_jobs(term="Analista de Dados"):
    url = f"https://www.vagas.com.br/vagas-de-{term.replace(' ', '-')}"
    headers = {"User-Agent": "Mozilla/5.0"}
    jobs = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
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
                    "description": f"Vaga de {title_elem.text.strip()} no Vagas.com",
                    "source": "Vagas.com"
                })
    except Exception as e:
        print(f"Erro Vagas.com: {e}")
    return jobs

# --- FILTRAGEM VIA IA ---

def is_job_relevant_with_ai(job_title, job_description):
    if not GEMINI_API_KEY:
        return True, "Sem API Key (Aprovação padrão)"

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
    Avalie se a seguinte vaga é RELEVANTE para o perfil desejado.
    Perfil Desejado: {PROFILE_TARGET}
    Filtro Negativo (Rejeitar): {NEGATIVE_KEYWORDS}

    Vaga: {job_title}
    Descrição: {job_description}

    Responda em formato JSON estrito:
    {{"relevant": true/false, "reason": "motivo curto"}}
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
        )
        data = json.loads(response.text)
        return data.get("relevant", False), data.get("reason", "")
    except Exception as e:
        return False, f"Erro IA: {e}"

# --- NOTIFICAÇÃO TELEGRAM ---

def send_telegram(job, reason):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[Aprovada Local] {job['title']} ({job['source']})")
        return

    msg = f"🎯 <b>Nova Vaga ({job['source']})!</b>\n\n📌 <b>Cargo:</b> {job['title']}\n🏢 <b>Empresa:</b> {job['company']}\n💡 <b>IA:</b> {reason}\n\n🔗 <a href='{job['link']}'>Ver Vaga</a>"
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    )

# --- EXECUÇÃO PRINCIPAL ---

def main():
    processed = load_processed_jobs()
    all_jobs = fetch_linkedin_jobs() + fetch_vagas_com_jobs()
    print(f"Total de vagas coletadas: {len(all_jobs)}")

    for job in all_jobs:
        if job["id"] in processed:
            continue

        relevant, reason = is_job_relevant_with_ai(job["title"], job["description"])
        if relevant:
            print(f"[APROVADA] {job['title']} - {job['source']}")
            send_telegram(job, reason)
        else:
            print(f"[REJEITADA] {job['title']} - Motivo: {reason}")

        processed.add(job["id"])

    save_processed_jobs(processed)

if __name__ == "__main__":
    main()
