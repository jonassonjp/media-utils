# Plano de atualização do `ajustar_datas.py`

Legenda: [ ] pendente · [x] concluído

## Fase 1 — Robustez e limpeza
- [x] 1.1 Saída amigável em Ctrl+C / Ctrl+D
- [x] 1.2 `os.stat().st_birthtime` e `os.utime` no lugar de `stat`/`touch` via subprocess
- [x] 1.3 Remover código morto (tratamento do `+` no modo 3, filtro de arquivo único)
- [x] 1.4 Não usar `.strip()` no caminho (só remover a quebra de linha do arrastar e soltar)
- [x] 1.5 Avisar quando a data é ajustada mas o arquivo não é renomeado (nome fora do padrão)
- [x] 1.6 `.gitignore` (`__pycache__`, `.DS_Store`)

## Fase 2 — Segurança dos dados
- [ ] 2.1 Registro para desfazer (`.json` com nomes e datas antigos) + modo "Desfazer"
- [ ] 2.2 Modo 3: aviso de efeito cumulativo e opção de usar a hora do nome como base
- [ ] 2.3 Modo 5: escolher o arquivo de referência

## Fase 3 — Funcionalidades
- [ ] 3.1 Corrigir EXIF/metadados de vídeo com exiftool (opcional nos modos 3, 4 e 5)
- [ ] 3.2 Prefixo `VID_` para vídeos
- [ ] 3.3 Argumentos de linha de comando (`--modo`, `--filtro`, `--dry-run`, `--sim`)
- [ ] 3.4 Detecção automática do fuso da câmera por pares foto/vídeo

## Fase 4 — Qualidade
- [ ] 4.1 Testes automatizados (`unittest`)
- [ ] 4.2 Separar interface e lógica
