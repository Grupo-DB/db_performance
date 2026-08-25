"""Settings para rodar testes que precisam do projeto INTEIRO (urls, DRF, todos os apps).

    venv/bin/python manage.py test controleQualidade.amostra.tests \
        --settings=db_performance.settings_teste_projeto

Diferente de `settings_teste.py`, que sobe só o app `whatsapp` e três dependências:
os testes de amostra batem nas rotas da API, então precisam do URLconf e dos apps
todos. Os nomes são parecidos de propósito — os dois existem porque o `settings.py`
aponta para o MySQL de PRODUÇÃO e `manage.py test` sem `--settings` criaria um
`test_db_manager` lá.

Duas trocas em relação ao settings normal:

* **SQLite em memória** — o `settings.py` aponta para o MySQL (o HOST não é
  commitado) e localmente não há banco.
* **sem migrations** — as migrations do projeto não constroem um banco novo: uma
  antiga do `catalogos` referencia `NewProduto.secao`, campo que já não existe, e
  o `migrate` do teste morre com FieldDoesNotExist. Desligando MIGRATION_MODULES
  o Django cria as tabelas direto dos models.

⚠️ O SQLite não reproduz tudo: `SELECT ... FOR UPDATE` é ignorado (a trava de
concorrência da numeração de amostra só existe no MySQL) e a collation dele é
sensível a acento e caixa, ao contrário da de produção.
"""
from db_performance.settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}


class SemMigrations:
    """Faz o test runner criar as tabelas dos models, sem aplicar migration."""

    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = SemMigrations()
