#!/usr/bin/env bash
# 27/11/2026 — Módulo Vistorias de veículos e equipamentos (app NOVO vistorias, migration 0001),
# escopo v2.1: programa anual, execução no celular (offline), validação com abono/devolução,
# suspensão por NC crítica com e-mail imediato, correção/liberação, Indicador mensal/trimestral.
# Rodar NA VM, como root, COM -t:
#   scp -P 2224 -r deploy/vistorias_2026-11-27 root@45.6.118.52:/root/
#   ssh -t -p 2224 root@45.6.118.52 'bash /root/vistorias_2026-11-27/deploy.sh'
# Antes: push do backend (app vistorias + db_performance/urls.py). O settings.py da VM NÃO é
# sobrescrito: o script só acrescenta 'vistorias' no INSTALLED_APPS.
# Pode rodar de novo: o que já foi feito é pulado.
set -euo pipefail
APP_DIR=/opt/manager_api
PY="$APP_DIR/venv/bin/python"
AQUI="$(dirname "$(readlink -f "$0")")"
cd "$APP_DIR"
etapa() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()    { printf '\033[1;32m   ok:\033[0m %s\n' "$*"; }
aviso() { printf '\033[1;33m   atenção:\033[0m %s\n' "$*"; }
erro()  { printf '\033[1;31m   ERRO:\033[0m %s\n' "$*"; exit 1; }
seguir() { read -r -p "   Seguir? [s/N] " r; [[ "$r" =~ ^[sS]$ ]] || { echo "   Parado a pedido."; exit 0; }; }
avisos() { grep -v -E 'W004|W340|W036|HINT|^$|WARNINGS|System check|STATICFILES|RuntimeWarning|warnings.warn' || true; }
aplicada() { "$PY" manage.py showmigrations "$1" 2>/dev/null | grep -q "\[X\] $2$"; }

etapa "0. Conferências"
echo "   Commit atual: $(git log -1 --format='%h %ad %s' --date=format:'%d/%m %H:%M')"
git fetch -q origin
echo "   Vai entrar:"; git log --format='     %h %ad %s' --date=format:'%d/%m' HEAD..origin/main || true
echo "   Alterações locais da VM (settings.py aparecer aqui é esperado):"
git status --short | grep -v '^??' | sed 's/^/     /' || true
USUARIO=$(systemctl show gunicorn -p User --value 2>/dev/null || true); USUARIO=${USUARIO:-root}
echo "   gunicorn roda como: $USUARIO"
seguir

etapa "1. git pull"
git pull --ff-only origin main
[ -f vistorias/models.py ] || erro "app vistorias não veio — falta o push."
grep -q "vistorias.urls" db_performance/urls.py || erro "db_performance/urls.py sem a rota vistorias/ — falta o push."
ok "agora em $(git log -1 --format='%h %s')"

etapa "2. INSTALLED_APPS"
if grep -q "'vistorias'" db_performance/settings.py; then ok "vistorias já estava"
else
  grep -q "^    'conformidadeLegal',$" db_performance/settings.py || erro "não achei a linha 'conformidadeLegal', — incluir 'vistorias' à mão no INSTALLED_APPS."
  cp db_performance/settings.py "/root/settings.py.antes_vistorias.$(date +%Y%m%d%H%M)"
  sed -i "s/^    'conformidadeLegal',$/    'conformidadeLegal',\n    'vistorias',/" db_performance/settings.py
  ok "vistorias incluído (cópia do settings em /root)"
fi
"$PY" manage.py check 2>&1 | avisos | sed 's/^/   /'

etapa "3. Pasta privada das fotos e vídeos (fora do /media, que o nginx serve sem login)"
PRIV="$APP_DIR/privado/vistorias"
mkdir -p "$PRIV"; chown -R "$USUARIO" "$APP_DIR/privado"; chmod 750 "$APP_DIR/privado" "$PRIV"
ok "$PRIV (dono $USUARIO, 750) — entra no backup diário junto com o banco (retenção mínima de 5 anos, seção 13)"

etapa "4. Migration (gitignored — copiada desta pasta)"
mkdir -p vistorias/migrations; touch vistorias/migrations/__init__.py
for f in "$AQUI"/migrations/vistorias/*.py; do
  nome=$(basename "$f"); destino="vistorias/migrations/$nome"
  if [ -f "$destino" ]; then
    cmp -s "$f" "$destino" && { ok "$nome já estava"; continue; }
    aplicada vistorias "${nome%.py}" && { ok "$nome já aplicada — mantida a da VM"; continue; }
    erro "$destino existe, é diferente e não está aplicada — conferir à mão."
  fi
  cp "$f" "$destino"; ok "$nome copiada"
done
# A 0001 da VM pode ser a versão que já trazia desenhos/foto/marcações (gerada depois do 1º commit):
# nesse caso as colunas da 0002 já existem e ela só é registrada (--fake).
if grep -q "ImagemTipo" vistorias/migrations/0001_initial.py && ! aplicada vistorias 0002_imagens_foto_marcacoes; then
  aviso "a 0001 da VM já cria ImagemTipo — 0002 registrada com --fake"
  "$PY" manage.py migrate vistorias 0002_imagens_foto_marcacoes --fake 2>&1 | grep -E 'Applying|FAKED|Error|error' | sed 's/^/   /' || true
fi
"$PY" manage.py migrate vistorias 2>&1 | grep -E 'Applying|No migrations|Error|error' | sed 's/^/   /' || true
"$PY" manage.py showmigrations vistorias 2>/dev/null | sed 's/^/   /'

etapa "5. Grupos (perfis da seção 2)"
"$PY" manage.py shell -c "
from django.contrib.auth.models import Group
for nome in ('VistoriaGestor', 'VistoriaAvaliador', 'VistoriaGerente', 'VistoriaPCM', 'VistoriaSESMT'):
    g, novo = Group.objects.get_or_create(name=nome)
    print('   ', nome, 'criado' if novo else 'já existia', '-', g.user_set.count(), 'usuário(s)')
" 2>&1 | grep '^    '
echo "   VistoriaGestor = Gerente Executivo Operacional/Diretoria. Os perfis também são dados na tela Vistorias → Cadastros → Usuários."

etapa "6. Fichas da planilha (Anexo A) e tipos de equipamento"
"$PY" manage.py carregar_fichas_vistoria 2>&1 | sed 's/^/   /'
aviso "a criticidade veio da pontuação da planilha (10 → crítica, 5 → média, 2,5 → leve). O GEO revisa em Cadastros → Fichas antes de começar."

etapa "6b. Equipamentos do SGA (tipo pelo prefixo da TAG; fotos são as mesmas de Peças da Oficina)"
"$PY" manage.py importar_equipamentos_sga 2>&1 | sed 's/^/   /'
echo "   Entram no setor \"A definir\" da unidade (FCB, ou ATM) e sem gerente: o GEO ajusta depois em Cadastros → Equipamentos."
read -r -p "   Importar esses equipamentos agora? [s/N] " r
if [[ "$r" =~ ^[sS]$ ]]; then "$PY" manage.py importar_equipamentos_sga --aplicar 2>&1 | head -1 | sed 's/^/   /'
else aviso "pulado — dá para importar depois pela tela (Cadastros → Equipamentos → Importar do SGA)."; fi

etapa "7. Cron dos e-mails pendentes (a cada minuto)"
CRON=/etc/cron.d/manager_vistorias
LINHA="* * * * * $USUARIO cd $APP_DIR && $PY manage.py enviar_emails_vistorias >> /var/log/manager_vistorias_emails.log 2>&1"
if [ -f "$CRON" ] && grep -qF "enviar_emails_vistorias" "$CRON"; then ok "$CRON já existia"
else printf 'SHELL=/bin/bash\n%s\n' "$LINHA" > "$CRON"; chmod 644 "$CRON"; ok "$CRON criado"; fi
echo "   O e-mail de suspensão sai na hora em que o avaliador informa o adesivo (ou em 2,5 min sem resposta); o cron cobre reinício do gunicorn e SMTP fora."

etapa "8. nginx: tamanho de upload (vídeo de até 30 s)"
CONF=$(grep -rl "manager_api\|managerdb.com.br" /etc/nginx/sites-enabled/ 2>/dev/null | head -1 || true)
if [ -n "$CONF" ]; then
  TAM=$(grep -h "client_max_body_size" "$CONF" /etc/nginx/nginx.conf 2>/dev/null | head -1 || true)
  echo "   client_max_body_size: ${TAM:-padrão do nginx (1m)}"
  echo "   Vídeo de 30 s do celular dá 10–60 MB: precisa de pelo menos 64M (Peças da Oficina já pede ≥ 210M)."
else aviso "não achei o site do nginx para conferir."; fi

etapa "9. Reiniciar gunicorn"
systemctl restart gunicorn
sleep 6
systemctl is-active gunicorn | sed 's/^/   gunicorn: /'

etapa "10. Fumaça"
for rota in painel/ programa/ vistorias/ evidencias/00000000-0000-0000-0000-000000000000/arquivo/; do
  c=$(curl -s -o /dev/null -w '%{http_code}' "https://managerdb.com.br/api/vistorias/$rota")
  echo "   GET /api/vistorias/$rota sem login → $c (esperado 401)"
done
"$PY" manage.py shell -c "
from vistorias.models import Ficha, TipoEquipamento
print('   fichas:', Ficha.objects.count(), '· tipos:', TipoEquipamento.objects.count())
" 2>&1 | grep '^   '

etapa "Pronto. Próximos passos"
echo "   1) Publicar o front (menu Controle Operacional → Vistorias; app: módulo Vistorias)."
echo "   2) GEO: Cadastros → Unidades e setores, Notificações (e-mails do GEO, SESMT e PCM), Usuários (perfis)."
echo "   3) GEO: revisar as fichas; cadastrar/importar do SGA os equipamentos; Programa → Gerar programa."
