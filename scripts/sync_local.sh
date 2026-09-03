#!/bin/bash
# Sincroniza home-vitrines.json rodando NESTA MAQUINA.
#
# Existe porque o GitHub Actions esta bloqueado por pendencia de cobranca desde
# 27/08/2026 ("your account is locked due to a billing issue"), e os crons que
# mantinham as vitrines e os precos da home pararam junto. Enquanto isso nao for
# resolvido, quem faz o trabalho e o launchd deste Mac (de hora em hora).
#
# Quando o Actions voltar, isto aqui pode ser desligado:
#   launchctl bootout gui/$(id -u)/br.com.pascoto.vitrines
#   rm ~/Library/LaunchAgents/br.com.pascoto.vitrines.plist
# Rodar os dois juntos nao quebra (ha pull --rebase antes do push), so e redundante.

set -uo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"
export GIT_SSH_COMMAND="/usr/bin/ssh -i $HOME/.ssh/id_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes"

REPO="$HOME/Projetos/pascoto-produtos-img-repo"
LOG="$HOME/Library/Logs/pascoto-vitrines.log"
STAMP="$REPO/.ultimo-catalogo"          # nao versionado: marca a ultima rodada do catalogo
CATALOGO_A_CADA=72000                   # 20h, pra imitar o cron diario do Actions

log() { echo "$(date '+%Y-%m-%d %H:%M:%S')  $*" >>"$LOG"; }

cd "$REPO" || { log "ERRO: repo nao encontrado em $REPO"; exit 1; }

# mantem o log em ate ~400 linhas
if [ -f "$LOG" ] && [ "$(wc -l <"$LOG")" -gt 400 ]; then
  tail -n 200 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

if ! /usr/bin/git pull --rebase --quiet origin main 2>>"$LOG"; then
  log "ERRO: git pull --rebase falhou, abortei sem mexer em nada"
  exit 1
fi

agora=$(date +%s)
ultimo=0
[ -f "$STAMP" ] && ultimo=$(cat "$STAMP" 2>/dev/null || echo 0)
if [ $((agora - ultimo)) -ge "$CATALOGO_A_CADA" ]; then
  if /usr/bin/python3 scripts/refresh_catalog.py >>"$LOG" 2>&1; then
    echo "$agora" >"$STAMP"
    log "catalogo (colecoes fantasma + precos) atualizado"
  else
    log "ERRO no refresh_catalog.py, sigo so com o update_vitrines"
  fi
fi

if ! /usr/bin/python3 update_vitrines.py >>"$LOG" 2>&1; then
  log "ERRO no update_vitrines.py, nao vou commitar"
  /usr/bin/git checkout -- home-vitrines.json 2>/dev/null
  exit 1
fi

/usr/bin/git add home-vitrines.json
if /usr/bin/git diff --cached --quiet; then
  log "sem mudanca"
  exit 0
fi

resumo=$(/usr/bin/git diff --cached --numstat home-vitrines.json | awk '{print $1" linhas alteradas"}')
/usr/bin/git -c user.name="sync local (Mac do Rodrigo)" \
             -c user.email="rpascotojr@gmail.com" \
             commit -q -m "chore: sync local das vitrines (Actions bloqueado por cobranca)"

for tentativa in 1 2 3; do
  if /usr/bin/git push --quiet 2>>"$LOG"; then
    log "PUBLICADO ($resumo) na tentativa $tentativa"
    exit 0
  fi
  log "push rejeitado, sincronizando..."
  /usr/bin/git pull --rebase --quiet origin main 2>>"$LOG" || { log "ERRO no rebase"; exit 1; }
done

log "ERRO: push falhou 3 vezes"
exit 1
