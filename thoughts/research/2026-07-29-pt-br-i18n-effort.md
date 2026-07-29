---
date: 2026-07-29T00:05:19-03:00
researcher: Guilherme Barbosa
git_commit: bd92f60a7768c2137424dc649de298162c8807e6
branch: main
repository: smiteless-br
topic: "Implementar tradução PT-BR de todo o projeto com troca de idioma via Settings — esforço?"
tags: [research, codebase, i18n, settings, smitesettings, smiteconfig, smitecard, draftboard, tags, loltempo]
status: complete
last_updated: 2026-07-29
last_updated_by: Guilherme Barbosa
---

# Research: Tradução PT-BR + troca de idioma via Settings — esforço?

**Date**: 2026-07-29 00:05:19 -03  
**Researcher**: Guilherme Barbosa  
**Git Commit**: bd92f60a7768c2137424dc649de298162c8807e6  
**Branch**: main  
**Repository**: smiteless-br

## Research Question

Quero implementar a tradução para PT-BR de todo este projeto para usuários do Brasil e dando a possibilidade de fazer a troca da lang via settings. É uma mudança com muito esforço?

## Summary

Hoje o Smiteless **não tem infraestrutura de i18n/l10n**. Todo o texto de produto está em **inglês hardcoded**, espalhado por módulos Python (boards PIL, coach, tags, Settings), AHK (tray/installer), DraftBoard HTML e `CHANGELOG.md`. Não existe chave `language`/`locale` em [`core/smiteconfig.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/smiteconfig.py); Settings só persiste toggles, sliders e strings de draft/max-elo.

A superfície de copy **owned pelo app** é da ordem de **centenas de literais/templates distintos**, concentrada em `smitecard.py`, frases de coach (`loltempo`/`loldead`/`lolqueue`/TTS), Settings e tags de scout. Além disso há conteúdo **externo em inglês por design**: Data Dragon fixo em `en_US`, tips MOBAFire/Claude, e patch notes.

**Resposta direta sobre esforço:** sim — traduzir “todo o projeto” com seletor de idioma em Settings é uma mudança de **esforço alto / multi-camada**, não um toggle isolado. O padrão existente de Settings tornaria *persistir* uma preferência de lang relativamente pequeno; o trabalho dominante é extrair/traduzir e religar texto em dezenas de superfícies (incluindo fixtures `tagcheck` que assertam strings renderizadas em inglês).

## Detailed Findings

### 1. Estado atual de i18n

- Nenhum `gettext`, `_()`, `.po`/`.mo`, pasta `locales/`, ou catálogo de mensagens.
- Busca por `lang`/`locale`/`i18n`/`pt-BR` no código de produto: só usos adjacentes (ex. voz TTS `"Salli"`, header HTTP `Accept-Language`, `<html lang="en">`).
- `STRINGS` em smiteconfig são chaves de **config** (`max_elo_main`, `draft_db`, …), não tabela de UI copy.
- Pasta `thoughts/`: sem documentos históricos sobre i18n (só scaffolds vazios).

### 2. Settings e persistência (onde um seletor de lang se encaixaria no modelo atual)

**Store:** [`core/smiteconfig.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/smiteconfig.py)  
- Arquivo: `~/.claude/smiteless_settings.json`  
- Modelo: `DEFAULTS`+`RANGES`, `BOOLS`, `STRINGS`, mais listas especiais (`ban_list`, swaps)  
- `load()` / `save()` com merge parcial e write atômico  

**UI:** [`ui/smitesettings.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/ui/smitesettings.py) (~834 linhas)  
- Abre com `cfg.load()`, grava no botão Save com `cfg.save({...})`  
- Inventário atual: MAX ELO, sliders, FEATURES (muitos checkboxes em inglês), auto-swap, perma-ban, accounts, flash key, startup, draft link, Riot API key  
- **Nenhuma** opção de idioma  

**Padrão existente para nova preferência (como o código já faz):** declarar em `DEFAULTS`/`BOOLS`/`STRINGS` → var Tk na Settings → incluir no dict do Save → consumidores leem via `cfg.load()`.

### 3. Superfícies com texto visível ao usuário

| Camada | Arquivos principais | Escala de copy | Forma |
|--------|---------------------|----------------|-------|
| Boards PIL | [`core/smitecard.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/smitecard.py) (~3667 linhas, ~195 `d.text`) | **LARGE** (~180–250 literais/templates) | Dicts parciais + inline |
| Settings Tk | `ui/smitesettings.py` | **LARGE** | Labels/blurbs inline |
| Outras UIs Tk | `smiteoverlay`, `smitewidget`, `smiteprofile`, `smiteload`, `smitedead`, `smitequeue`, `smitenotes` | **MEDIUM** no conjunto | Títulos, status, headers |
| Coach ao vivo | `loltempo`, `loldead`, `lolreentry`, `lolqueue` | **LARGE** juntos | Dicts + f-strings |
| Tags scout | `lolload._profile_tags` + [`docs/TAGS.md`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/docs/TAGS.md) | **MEDIUM** | Templates EN; spec = forma renderizada |
| Champ tags | `loltags.py` | SMALL–MEDIUM | `_SHORT` / `_PHRASES` EN |
| DraftBoard web | [`docs/draft/index.html`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/docs/draft/index.html) | **MEDIUM** chrome + data EN | Chrome HTML; payload já vem com strings prontas |
| Tray / installer | `smiteless.ahk`, `dist/tray.ahk`, `dist/installer.ahk`, `tools/smiteless_tray.py` | **SMALL** | Menus ~15–25 itens |
| Patch notes | `CHANGELOG.md` + `smitenotes.py` | **LARGE** (conteúdo) | Markdown EN, sem tradução |
| TTS | `ui/smitewidget.py` `_TEMPO_SPEECH` | SMALL | Voz Polly US English |
| Matchup / LLM | `lolmatchup`, `lolcoach` | MEDIUM+ | Scrapes/prompts EN |
| Data Dragon | `lolbuild.py`, DraftBoard | catálogo Riot | URL fixa `…/data/en_US/…` |

**Dispatch:** [`smiteless_main.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/smiteless_main.py) roteia `settings`, `overlay`, `widget`, `dead`, `load`, `queue`, `profile`, `notes`, etc.

### 4. Como o texto dinâmico é construído hoje

Padrão dominante: **montar inglês no Python → UI só exibe**.

Exemplos documentados:

- **Queue Call** — `_INSTRUCTION` + headlines/subs em [`core/lolqueue.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/lolqueue.py); UI em `ui/smitequeue.py` só pinta `verdict`/`headline`/`sub`/`lines`.
- **Tempo** — f-strings de fase em [`core/loltempo.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/loltempo.py) + tabela TTS paralela `_TEMPO_SPEECH` em `ui/smitewidget.py`.
- **Death brief** — `_COUNTER` + templates em [`core/loldead.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/loldead.py).
- **Player tags** — f-strings em [`core/lolload.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/lolload.py) (`off-champ · …`, `smurf? · …`, `XW heater`); spec canônica em `docs/TAGS.md`; guards em `tools/tagcheck.py` validam **texto renderizado**.
- **DraftBoard** — [`core/loldraft.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/loldraft.py) envia `t`, `tip`, `plan`, `wincons`, `threat.txt` já em inglês; a página escapa/renderiza (com alguns fallbacks EN no HTML).

### 5. Dimensões extras que ampliam o escopo de “tudo”

| Dimensão | Estado atual |
|----------|--------------|
| Spec + testes de tags | `TAGS.md` e `tagcheck` acoplados às strings EN exibidas |
| Glyphs / fontes | `tools/glyphcheck.py` — texto PT-BR (acentos) passa por fontes do skin Duskfall |
| Nomes Riot (itens, runas, spells, champs) | Fixos em locale CDN `en_US` no app e no DraftBoard |
| Conteúdo gerado/externo | Tips MOBAFire, prompts Claude, CHANGELOG |
| DraftBoard deploy | Página estática em GitHub Pages; chrome + hidratação `en_US` no cliente |
| Invariantes de produto | Grades = só performance in-game; tags citam evidência; DraftBoard side-by-side — independentes de idioma, mas tags traduzidas precisam preservar o contrato de evidência |

### 6. Caracterização de esforço (resposta à pergunta)

Com base no que existe hoje:

| Fatia | Natureza do trabalho implícito pelo estado atual | Ordem de esforço |
|-------|--------------------------------------------------|------------------|
| Preferência `lang` em smiteconfig + controle na Settings | Encaixa no padrão BOOLS/STRINGS + Save já existente | **Baixo** (em isolamento) |
| Chrome Settings + trays AHK/Python | Dezenas de labels literais | **Baixo–médio** |
| Boards `smitecard` + headers de overlays | Centenas de literais, muitos inline em renderers | **Alto** |
| Coach (tempo/dead/queue/reentry/TTS) | Templates + f-strings + voz | **Alto** |
| Tags scout + `TAGS.md` + `tagcheck` | Spec = copy; fixtures assertam EN | **Médio–alto** (inclui guards) |
| DraftBoard HTML + payload | Chrome web + strings pré-montadas no cliente | **Médio** |
| Data Dragon `pt_BR` | Troca de path de locale (nomes Riot) | **Baixo** tecnicamente; decisão de produto (EN vs PT nos nomes) |
| CHANGELOG / patch notes bilíngues | Fonte única EN hoje | **Médio** se “tudo” incluir notas |
| Matchup scrape / LLM coach | Conteúdo nasce em EN fora do app | **Alto / aberto** se “tudo” incluir tips e coach LLM |

**Veredito:** para o pedido literal (“todo o projeto” + troca via Settings), o esforço é **alto** — não porque Settings seja difícil, mas porque **não há camada de strings** e a copy está acoplada à lógica de coaching/tags em muitos módulos. Um seletor de idioma sozinho não muda o idioma da UI até essa superfície ser coberta.

## Code References

- [`core/smiteconfig.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/smiteconfig.py) — store de prefs; sem chave de idioma  
- [`ui/smitesettings.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/ui/smitesettings.py) — UI Settings (copy EN)  
- [`core/smitecard.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/smitecard.py) — maior superfície visual de texto  
- [`core/lolload.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/lolload.py) — templates de player tags / plan / wincons  
- [`docs/TAGS.md`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/docs/TAGS.md) — spec canônica das tags (texto = UI)  
- [`core/loltempo.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/loltempo.py), [`core/loldead.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/loldead.py), [`core/lolqueue.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/lolqueue.py) — frases de coach  
- [`core/loldraft.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/loldraft.py) + [`docs/draft/index.html`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/docs/draft/index.html) — payload e chrome DraftBoard  
- [`core/lolbuild.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/core/lolbuild.py) — Data Dragon `en_US`  
- [`smiteless.ahk`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/smiteless.ahk), [`dist/tray.ahk`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/dist/tray.ahk) — menus tray  
- [`CHANGELOG.md`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/CHANGELOG.md) + [`ui/smitenotes.py`](https://github.com/GFBarbosa/smiteless-br/blob/bd92f60a7768c2137424dc649de298162c8807e6/ui/smitenotes.py) — patch notes EN  

## Architecture Documentation

- **UI text flow:** lógica em `core/` (e alguns `tools/`) produz strings prontas; `ui/` e DraftBoard renderizam.  
- **Prefs:** JSON flat + marker files/registry para startup; consumers re-leem `cfg.load()`.  
- **Design system:** `core/smiteskin.py` (fontes/cores), não strings.  
- **Guards:** `tagcheck` / `glyphcheck` / `selftest` acoplados ao texto e glifos atuais.  
- **Sem camada de locale:** idioma implícito = inglês em todos os caminhos user-facing.

## Historical Context (from thoughts/)

Nenhum documento em `thoughts/` sobre i18n, PT-BR ou language settings. Adjacente fora de thoughts: `docs/UIDESIGN.md` (spec visual da Settings), `docs/DRAFTLINK.md` (prefs de draft), `README.md` (nota do fork `GFBarbosa/smiteless-br` — workflow, não i18n de produto).

## Related Research

Nenhum documento prévio em `thoughts/research/`.

## Open Questions

- Escopo de “todo”: inclui CHANGELOG, tips MOBAFire, saída do Claude coach, e nomes Riot via `pt_BR` Data Dragon, ou só chrome/coach owned pelo app?  
- Tags traduzidas: a spec/`tagcheck` passam a validar as formas PT-BR (ou ids estáveis + label display)?  
- DraftBoard compartilhado: idioma segue a preferência do host que publicou o draft, ou a página tem seletor próprio?  
- TTS: voz PT-BR no mesmo pipeline ttsmp3/Polly, ou só texto escrito muda?
