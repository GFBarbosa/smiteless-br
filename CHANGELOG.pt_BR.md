# Smiteless — Notas da atualização

## Próximas versões

- Interface, boards e coaching respeitam o idioma selecionado.

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
