from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Todas as configurações vêm só daqui. Nenhum endereço e nenhuma chave no
    código, senão mudar de servidor vira uma caça a valores fixos no código."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://boss:boss@db:5432/boss"
    redis_url: str = "redis://redis:6379/0"
    secret_encryption_key: str = ""
    auth_secret: str = ""
    # A lista de todos os endpoints da API não deve ficar exposta. Ligar só para depuração.
    docs_enabled: bool = False
    anthropic_api_key: str = ""
    # anthropic — Claude com chave; gemini — Google com chave;
    # openrouter — cadeia de modelos; ollama — modelo local na própria máquina.
    ai_provider: str = "anthropic"
    ollama_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.2:3b"
    # OpenRouter: uma chave, cadeia de modelos separados por vírgula. Acabou o
    # limite do primeiro — a requisição passa sozinha para o próximo.
    openrouter_api_key: str = ""
    openrouter_models: str = ""
    # Gemini: chave do Google AI Studio, cadeia de modelos separados por vírgula.
    # Cada modelo tem seus limites — acabou no primeiro, responde o próximo.
    gemini_api_key: str = ""
    gemini_models: str = "gemini-3.6-flash,gemini-3.5-flash,gemini-2.5-flash,gemini-3.1-flash-lite"
    # Se a chave do servidor é compartilhada com quem se cadastrou sozinho e
    # não colou a própria chave do Gemini. A equipe (owner) usa a chave do
    # servidor sempre. false — desconhecidos só usam a própria chave, e o
    # e-mail deles não gasta as suas requisições.
    ai_shared_key: bool = False
    # Se o cadastro pelo link está aberto. false — logins só são criados
    # pela equipe no servidor (python -m app.admin add).
    registration_open: bool = True
    # Fazer a triagem só dos e-mails a partir desta data (AAAA-MM-DD). Anos
    # de conversa antiga não pedem decisão, e triar cada e-mail custa tempo
    # e limites. Vazio — triar tudo.
    classify_since: str = ""
    # Com o que traduzir os e-mails no botão «Traduzir»:
    # libretranslate — tradutor próprio no servidor (contêiner translator),
    # grátis e sem rede neural; ai — o mesmo modelo que faz a triagem
    # (melhor qualidade, mas gasta requisições).
    translator: str = "libretranslate"
    libretranslate_url: str = "http://translator:5000"
    # DeepL API Free: a melhor tradução sem rede neural própria, 500 000
    # caracteres por mês grátis. Com chave, quem traduz é o DeepL; acabou a
    # cota do mês ou o DeepL não respondeu — o tradutor próprio
    # (libretranslate). Vazio — direto o próprio.
    deepl_api_key: str = ""
    # Quantos caracteres do DeepL por dia cabem a cada pessoa que se cadastrou
    # sozinha (member). A cota mensal é uma só para o servidor inteiro: sem
    # este teto, um desconhecido clicando «Traduzir» a esgota em uma tarde.
    # Passou do teto — traduz o tradutor próprio. A equipe (owner) não tem teto.
    deepl_member_daily_chars: int = 20000
    # Resumo matinal: a que horas (no TZ) montá-lo e para onde mandá-lo por
    # e-mail. Vazio — não mandar; o resumo fica só na tela «Resumo».
    brief_hour: int = 7
    brief_email_to: str = ""
    s3_endpoint: str = "http://minio:9000"
    s3_bucket: str = "attachments"
    s3_user: str = "boss"
    s3_password: str = ""


settings = Settings()
