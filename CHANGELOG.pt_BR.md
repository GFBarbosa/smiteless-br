# Smiteless — Notas da atualização

## Próximas versões

- Interface, boards e coaching respeitam o idioma selecionado.

## v0.9.69 — THE WARD CLOCK amadurece: o prazo, seu amuleto e os 75 de ouro esquecidos

**Uma grande evolução do guard lançado na versão anterior, nos quatro pontos em que ainda
faltava informação para selva e suporte.**

- **O prazo, não apenas a contagem regressiva.** Uma sentinela colocada quando o dragão nasce
  é decoração. O cartão **PIT** agora usa o mesmo relógio de objetivos do app para informar
  até quando a visão precisa estar no covil:

      PIT — dragão em 68 s · visão até 9:23 e nenhuma visão sua está viva    1:00

  Nos últimos segundos, o prazo desaparece e a instrução passa a ser agir agora.
- **O amuleto na sua mão muda a instrução.** Com lente do oráculo, remova a visão inimiga
  antes de colocar a sua. Com alteração vidente, posicione à distância e nunca receba uma
  ordem impossível de varrer. O amuleto amarelo não acrescenta uma frase inútil.
- **A sentinela de controle virou um histórico, não uma foto.** Como a queda da contagem no
  inventário é a evidência de que uma sentinela foi colocada, o app acompanha os dois lados:

      1 de 2 colocadas · sentinela de controle com você em 42% da partida

  Essa porcentagem mede a parcela observada da partida em que você carregou controle de mapa.
  Ela não aparece antes de existir uma amostra de um minuto e nunca sai do intervalo 0–100%.
- **A compra aparece quando pode virar ação.** Durante um retorno à base, sem sentinela de
  controle e com pelo menos 75 de ouro, a linha começa com `+75 de ouro: sentinela de
  controle`. O pedido não aparece para quem já carrega uma nem para quem não pode comprá-la.
- **Agora há voz:** “Coloque visão.”, no máximo três vezes por partida, seguindo o mesmo
  contrato de chamadas do BLEED. A chave interna de cache de áudio continua sendo `wardit`.

As proteções anteriores permanecem: o guard só arma depois que o feed prova que fornece
pontuação de visão; tempo morto não aumenta nem reinicia o relógio de escuridão; decisões de
luta do coach de ritmo têm precedência; BLEED, RE-ENTRY e CLOSER mantêm seus cartões; e todas
as três rotas permanecem silenciosas.

**Testes:** 24 fixtures e seis partidas simuladas cobrem prazo, amuletos, histórico de pinks,
compra na base, limites da porcentagem, payloads malformados, arming do feed, congelamento
durante a morte, lobbies ambíguos e silêncio completo para laners. O histórico de uma partida
de 25 minutos confirma duas sentinelas compradas, uma colocada e 40% do tempo carregando uma.

## v0.9.68 — THE WARD CLOCK: a disputa de visão ao vivo e o último vazamento do histórico

**Novo recurso. Todas as tags que o perfil pode atribuir agora têm uma superfície que age
enquanto o erro ainda pode ser evitado.**

`no vision setup` era a última tag sem resposta dentro da partida. O GOLD CLOCK é
deliberadamente silencioso para selva e suporte; por isso, o WARD CLOCK pertence justamente
às duas funções responsáveis pelo mapa.

- **É medição, não palpite.** A porta `:2999` fornece a pontuação de visão dos dez jogadores.
  Como ela só aumenta enquanto uma sentinela sua está viva, 1:40 sem mudança prova que não há
  visão sua ativa no mapa.
- **Comparação direta da mesma função.** A linha discreta mostra sua pontuação contra a do
  suporte ou caçador inimigo, além da taxa por minuto e da meta do perfil:

      WARD   14,2 x 21,6 · 0,9/min, meta 1,2 · 1 pink

  As metas continuam sendo 1,2/min para suporte e 0,55/min para selva, lidas da mesma fonte
  usada pela tag `no vision setup`.
- **PIT — a luta que seria feita às cegas.** Na janela de aproximadamente 75 segundos antes
  de dragão, Vastilarvas, Arauto ou Barão, 45 segundos sem visão bastam para o cartão assumir.
  Ele indica onde colocar: além do covil quando o time está à frente, ou no próprio arbusto
  triangular e na entrada do covil quando está atrás.
- **DARK** aparece brevemente após 1:40 sem pontuação nova. **PINK** aparece uma vez quando uma
  sentinela de controle comprada permanece dois minutos na mochila. **WARD** é a linha
  discreta permanente.
- O guard permanece adormecido até observar uma pontuação de visão diferente de zero em algum
  jogador. Se a Riot remover o campo ou uma fila não o fornecer, toda a superfície degrada
  para silêncio.
- Tempo na tela cinza não é cobrado. O coach de ritmo recebe a decisão de luta, e BLEED,
  RE-ENTRY e CLOSER preservam precedência.
- Apenas selva e suporte. Topo, meio e atirador nunca recebem uma avaliação de visão inventada.
- Ativado por padrão em **Configurações → Relógio de visão (disputa de visão, selva /
  suporte)**, incluído no MAX ELO e na legenda do widget.

**Testes:** 419.160 asserções antes do lançamento, além dos guards permanentes do self-test.
Foram cobertos função, relógio, pontuação, escuridão, inventário, objetivo, fase do coach,
estado de arming, comparação ambígua, quatro janelas de morte, sentinela
comprada/carregada/colocada, payloads malformados e renderização real de todos os quadros.

## v0.9.67 — THE GOLD CLOCK: sua rota comparada aos minions que realmente nasceram

**Novo recurso para o maior vazamento do histórico que ainda não tinha resposta durante a
partida: a economia fraca nos primeiros dez minutos.**

A tag `weak first-ten economy` exige terminar 10:00 abaixo de 55 de farm **e** 3.100 de ouro.
Quatro funções podem recebê-la, mas antes nenhuma superfície ajudava enquanto ainda era
possível corrigir o ritmo.

- **A conta usa o cronograma real.** A primeira onda sai em 1:05 e outra sai a cada 30
  segundos; cada onda tem três minions corpo a corpo e três conjuradores, e cada terceira
  leva um canhão. A onda só entra no denominador quando chega à rota: meio em 1:30 e laterais
  em 1:38.

      OURO   41 de 74 · 55% · projeção 63, meta 55

  Minions corpo a corpo valem 21 de ouro, conjuradores 14 e canhões 60. Esses valores ficam
  estáveis até 15:00, portanto toda a janela pode ser calculada exatamente.
- **A meta é calculada de trás para frente.** A partir dos 55 aos 10:00, o cartão informa o
  que precisa ser coletado:

      MISS — a onda passou · projeção de 42 em 10:00, meta 55
      você precisa de 25 dos próximos 32 minions (78%)

  Quando a recuperação apenas pelas ondas se torna impossível, mostra quantos minions faltam
  e troca o plano para placas, acampamentos e objetivos.
- **O canhão tem relógio.** O aviso **CANNON** aparece segundos antes da chegada do minion de
  60 de ouro, mas somente quando o jogador está abaixo da meta.
- **Roaming não parece farm ruim.** Abates e assistências são convertidos em farm equivalente
  usando a mesma constante do modelo de ouro ao vivo. Assim, 30 de farm e três abates podem
  aparecer como `30+44 de 82 · 90%` e permanecer acima da meta.
- Ondas perdidas durante a morte não são cobradas. BLEED mantém precedência sobre uma onda
  perdida, e uma chamada de objetivo ao vivo mantém precedência sobre o GOLD CLOCK.
- **PACE** é uma linha discreta durante toda a janela. O cartão só aparece quando uma onda é
  perdida ou um canhão está chegando.
- Apenas topo, meio e atirador. Selva e suporte permanecem silenciosos.
- Ativado por padrão em **Configurações → Relógio de ouro (ritmo de farm, primeiros 10 min)**,
  incluído no MAX ELO e na legenda do widget.

**Testes:** 10.721 asserções validam o nascimento e a chegada das ondas, o relógio dos canhões,
o ouro por minion, a conversão de ouro para farm, todos os vereditos, quatro partidas
simuladas, silêncio para funções excluídas, ondas durante a morte e payloads malformados.
Todos os quadros produzidos pelo guard foram renderizados pelo caminho real do widget.

## v0.9.66 — THE CLOSER: as partidas que você estava vencendo e perdeu

**Novo recurso que só aparece quando seu time já está vencendo.** A partir dos 20 minutos,
com pelo menos 2 mil de vantagem, o CLOSER lê torres, inibidores, vantagem de luta e o tempo
real da sua morte para mostrar o caminho mais curto até o nexus.

- Mantém um mapa estrutural ao vivo e avisa quando é hora de terminar, cercar um inibidor ou
  derrubar a última torre que o protege.
- Mostra quanto da maior vantagem o time já devolveu. Após devolver 1,5 mil, fica mais
  conservador porque o time não precisa de outra luta, precisa do nexus.
- Converte a morte em custo real: por exemplo, 51 segundos e um Barão entregue.
- Quando não há urgência, mostra apenas uma linha discreta com a vantagem. Atrás ou empatado,
  não aparece.
- As instruções são próprias do fim da partida e respeitam a leitura do coach de ritmo.
- Ativado por padrão em **Settings → Finalizador (converter vantagem, após 20:00)**, com uma
  nova seção explicativa na legenda do widget.

Foram adicionadas 60 asserções para o parser de estruturas, relógio dos inibidores, doze
ramificações de veredito, linha do tempo simulada e payloads malformados. O self-test também
passou a proteger o BLEED GUARD.

## v0.9.65 — as runas se adaptam ao lobby, não apenas ao campeão

- A importação automática escolhe entre páginas reais do op.gg conforme a composição inimiga.
  Contra linha de frente pesada, favorece páginas de dano sustentado; contra alvos frágeis,
  páginas de explosão.
- A adaptação só ocorre com uma composição inequívoca: pelo menos dois tanques ou três
  integrantes de linha de frente, ou nenhum tanque e quatro alvos frágeis.
- Leituras mistas, menos de três inimigos confirmados ou páginas com amostra pequena mantêm a
  página mais usada.
- O painel mostra a justificativa completa, incluindo campeões, taxas de vitória e amostras.
- A escolha manual de uma página continua tendo prioridade.

## v0.9.64 — o recomendador entende seu desempenho pessoal, e Fantasma usa a tecla do Flash

- Na ausência de Flash, Fantasma passa a ocupar a tecla de mobilidade escolhida. Se a build
  tiver os dois, Flash mantém essa tecla.
- Campeões com resultados pessoais comprovadamente ruins podem ser vetados. São exigidas
  amostra mínima e aproximadamente 80% de confiança; três derrotas não bastam.
- Campeões jogados abaixo da sua média são rebaixados com a evidência numérica.
- Campeões em que você joga bem, mas não usa há várias partidas, são promovidos como uma
  alternativa segura à vontade de estrear algo novo.
- O painel mostra `DESCANSADO` ou `EM BAIXA` junto do histórico que motivou o ajuste.
- O auto-lock do MAX ELO usa o mesmo filtro. A leitura sazonal é armazenada em cache e
  atualizada fora do loop do draft.

## v0.9.63 — o silêncio automático espera suas mãos pararem e aborta ao primeiro toque

- O helper distingue teclas e cliques reais dos eventos que ele mesmo injeta e interrompe o
  comando imediatamente se o usuário tocar no teclado ou mouse.
- Ele só começa após cerca de 350 ms de inatividade real.
- Movimento do cursor e rolagem não contam como interferência; cliques contam.
- O League não oferece um atalho configurável para “silenciar todos”, então a digitação foi
  protegida contra interferência.
- O self-test cobre teclas, cliques, movimento, rolagem, eventos injetados e liberação dos
  hooks.

## v0.9.62 — silêncio automático reforçado: havia três cópias digitando ao mesmo tempo

- Foi restaurado o mutex de instância única e adicionado um lock interno de envio, impedindo
  comandos simultâneos de se misturarem.
- Se a tentativa na fonte falhar, o helper pode tentar novamente apenas enquanto seu campeão
  estiver morto, uma janela em que uma tecla perdida não movimenta nem conjura habilidades.
- O foco é verificado antes de cada caractere e o chat é fechado quando há aborto.
- A camada de configurações do cliente também oculta os canais e zera o volume de pings, com
  leitura de confirmação.

## v0.9.61 — MAX ELO confirma o campeão que indicou

- A recomendação deixava de considerar estável o campeão já indicado e alternava o alvo a
  cada poll, reiniciando indefinidamente o relógio de confirmação.
- “BONS NESTA PARTIDA” não trata mais seu próprio hover como uma escolha indisponível.
- Quando um campeão está no seu slot, é esse campeão que o MAX ELO confirma. Um erro
  momentâneo de rede não apaga mais o compromisso.
- O comportamento foi validado com uma lista cuja ordem muda em todos os polls.

## v0.9.60 — MAX ELO tenta apenas campeões que você pode escolher

- O auto-lock consulta `pickable-champion-ids`, que considera propriedade, rotação gratuita e
  bans, antes de tentar confirmar.
- Um campeão recusado três vezes é abandonado e o próximo da lista é tentado.
- A lista passou de cinco para doze opções para sobreviver a bans e restrições de propriedade.
- “BONS NESTA PARTIDA” também oculta campeões que o cliente recusaria, sem restaurar o antigo
  bloqueio por maestria.
- O self-test cobre campeão principal não possuído, lista vazia e propriedade completa.

## v0.9.59 — MAX ELO sem campeão definido escolhe a melhor opção do draft

- Principal e Reserva podem ficar vazios. Nesse modo, o MAX ELO confirma a melhor escolha para
  a composição atual usando a mesma leitura de “BONS NESTA PARTIDA”.
- Definir Principal e Reserva continua prendendo o auto-lock a esses campeões.
- Se a primeira opção estiver banida ou escolhida, a lista já funciona como cadeia de backup.

## v0.9.58 — silêncio automático digita uma vez na fonte e nunca durante o movimento

- A segunda tentativa aos 25 segundos foi removida porque um clique podia tirar o foco do chat
  e fazer o `f` de `fullmute` conjurar Flash.
- Há uma única tentativa por volta de 4 segundos, enquanto o campeão ainda está parado na
  fonte, e nenhuma digitação após 20 segundos.
- A camada persistente de configurações do cliente permanece como fallback.
- O self-test impede que uma segunda tentativa ou uma janela tardia sejam reintroduzidas.

## v0.9.57 — a seleção recomenda o que é BOM, não apenas o que você já possui em maestria

- “BONS NESTA PARTIDA” passou a usar o mesmo algoritmo do DraftBoard: counters das escolhas
  confirmadas e encaixe de composição, sem o bloqueio rígido de 12 mil pontos de maestria.
- O alerta de subida continua aparecendo quando você indica um campeão pouco conhecido; apenas
  a recomendação deixou de esconder opções fortes.
- Os rostos sugeridos continuam clicáveis para indicar o campeão.

## v0.9.56 — o silêncio automático funciona: faltava o scan code do Enter

- O Enter que abre o chat passou a ser enviado como scan code `0x1C`, assim como os demais
  caracteres. Antes ele era ignorado e as letras atingiam os atalhos do campeão.
- A conclusão anterior sobre bloqueio de input pelo anti-cheat estava errada; os eventos
  injetados chegam ao jogo quando são formados corretamente.
- As duas camadas foram mantidas: `/fullmute all` para chat e marcadores de ping naquela
  partida, e configurações do cliente para chat e áudio como fallback persistente.
- O self-test falha se o Enter perder novamente seu scan code.

## v0.9.55 — silêncio automático verificável pelas configurações do cliente

- A primeira solução substituiu a digitação por configurações oficiais do cliente: chat
  aliado oculto, chat geral oculto e áudio dos pings silenciado.
- Cada alteração é relida para confirmar que o cliente a aceitou.
- Os marcadores visuais de ping continuam no minimapa porque o cliente não expõe uma opção
  para escondê-los.
- Essas preferências persistem até serem desligadas no Smiteless ou no League;
  `python core\lolmute.py off` reverte a camada persistente.
- O self-test passou a ler o estado real e deixou de escrever entradas falsas no log de
  auto-lock.
