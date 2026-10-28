"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { api, formatConfidence, formatCost } from "@/lib/api";
import type { JudgeChatTurn } from "@/lib/types";

interface SpeechResultEvent {
  resultIndex: number;
  results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }>;
}

interface SpeechErrorEvent { error: string; }

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechResultEvent) => void) | null;
  onerror: ((event: SpeechErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}

interface RealtimeFunctionCall {
  type: "function_call";
  name?: string;
  call_id?: string;
  arguments?: string;
}

interface RealtimeServerEvent {
  type?: string;
  error?: { message?: string };
  response?: { status?: string; output?: RealtimeFunctionCall[] };
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;
type NaturalVoicePhase =
  | "IDLE"
  | "CONNECTING"
  | "LISTENING"
  | "USER_SPEAKING"
  | "PROCESSING"
  | "ANALYZING"
  | "RESPONDING"
  | "ERROR";

function speechRecognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const browserWindow = window as typeof window & {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  };
  return browserWindow.SpeechRecognition ?? browserWindow.webkitSpeechRecognition ?? null;
}

export function JudgeChat({
  projectId,
  turns,
  disabled,
  blockReason,
  onSend,
}: {
  projectId: string;
  turns: JudgeChatTurn[];
  disabled: boolean;
  blockReason: string | null;
  onSend: (message: string, inputMode: "TEXT" | "VOICE") => Promise<JudgeChatTurn>;
}) {
  const [draft, setDraft] = useState("");
  const [listening, setListening] = useState(false);
  const [voiceCaptured, setVoiceCaptured] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(false);
  const [naturalVoiceSupported, setNaturalVoiceSupported] = useState(false);
  const [naturalVoicePhase, setNaturalVoicePhase] = useState<NaturalVoicePhase>("IDLE");
  const [naturalVoiceModel, setNaturalVoiceModel] = useState<string | null>(null);
  const [naturalVoiceName, setNaturalVoiceName] = useState<string | null>(null);
  const [speakReplies, setSpeakReplies] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [interimTranscript, setInterimTranscript] = useState("");
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const shouldListenRef = useRef(false);
  const restartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const dataChannelRef = useRef<RTCDataChannel | null>(null);
  const microphoneStreamRef = useRef<MediaStream | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
  const naturalVoiceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const naturalVoiceActiveRef = useRef(false);
  const toolRunningRef = useRef(false);
  const handledCallIdsRef = useRef(new Set<string>());

  const naturalVoiceActive = !["IDLE", "ERROR"].includes(naturalVoicePhase);

  useEffect(() => {
    setSpeechSupported(Boolean(speechRecognitionConstructor()));
    setNaturalVoiceSupported(Boolean(
      typeof window !== "undefined"
      && "RTCPeerConnection" in window
      && navigator.mediaDevices?.getUserMedia,
    ));
    return () => {
      shouldListenRef.current = false;
      if (restartTimerRef.current) clearTimeout(restartTimerRef.current);
      recognitionRef.current?.stop();
      releaseNaturalVoiceResources();
    };
  }, []);

  useEffect(() => {
    if (!disabled || !shouldListenRef.current) return;
    shouldListenRef.current = false;
    if (restartTimerRef.current) clearTimeout(restartTimerRef.current);
    recognitionRef.current?.stop();
    setListening(false);
    setInterimTranscript("");
  }, [disabled]);

  function releaseNaturalVoiceResources() {
    naturalVoiceActiveRef.current = false;
    toolRunningRef.current = false;
    if (naturalVoiceTimerRef.current) {
      clearTimeout(naturalVoiceTimerRef.current);
      naturalVoiceTimerRef.current = null;
    }
    microphoneStreamRef.current?.getTracks().forEach((track) => track.stop());
    microphoneStreamRef.current = null;
    dataChannelRef.current?.close();
    dataChannelRef.current = null;
    peerRef.current?.close();
    peerRef.current = null;
    if (remoteAudioRef.current) {
      remoteAudioRef.current.pause();
      remoteAudioRef.current.srcObject = null;
    }
    remoteAudioRef.current = null;
    handledCallIdsRef.current.clear();
  }

  function stopNaturalVoice() {
    releaseNaturalVoiceResources();
    setNaturalVoicePhase("IDLE");
    setNaturalVoiceModel(null);
    setNaturalVoiceName(null);
  }

  async function startNaturalVoice() {
    if (disabled || naturalVoiceActive || !naturalVoiceSupported) return;
    stopListening();
    window.speechSynthesis?.cancel();
    releaseNaturalVoiceResources();
    naturalVoiceActiveRef.current = true;
    setNaturalVoicePhase("CONNECTING");
    setVoiceError(null);

    try {
      const session = await api.createJudgeVoiceSession(projectId);
      if (!naturalVoiceActiveRef.current) return;
      setNaturalVoiceModel(session.model);
      setNaturalVoiceName(session.voice);

      const peer = new RTCPeerConnection();
      peerRef.current = peer;
      const remoteAudio = document.createElement("audio");
      remoteAudio.autoplay = true;
      remoteAudioRef.current = remoteAudio;
      peer.ontrack = (event) => {
        remoteAudio.srcObject = event.streams[0] ?? new MediaStream([event.track]);
        void remoteAudio.play().catch(() => {
          setVoiceError("O navegador bloqueou o áudio. Clique novamente em iniciar a conversa.");
        });
      };
      peer.onconnectionstatechange = () => {
        if (!naturalVoiceActiveRef.current || peer.connectionState !== "failed") return;
        releaseNaturalVoiceResources();
        setNaturalVoicePhase("ERROR");
        setVoiceError("A conexão de voz foi interrompida. Tente iniciar novamente.");
      };

      const microphone = await navigator.mediaDevices.getUserMedia({
        audio: {
          autoGainControl: true,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      if (!naturalVoiceActiveRef.current) {
        microphone.getTracks().forEach((track) => track.stop());
        return;
      }
      microphoneStreamRef.current = microphone;
      microphone.getAudioTracks().forEach((track) => peer.addTrack(track, microphone));

      const channel = peer.createDataChannel("oai-events");
      dataChannelRef.current = channel;
      channel.onopen = () => {
        if (naturalVoiceActiveRef.current) setNaturalVoicePhase("LISTENING");
      };
      channel.onmessage = (event: MessageEvent<string>) => {
        void handleRealtimeEvent(event.data);
      };
      channel.onerror = () => {
        setVoiceError("Houve uma falha no canal da conversa por voz.");
      };

      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      const sdpResponse = await fetch("https://api.openai.com/v1/realtime/calls", {
        method: "POST",
        body: offer.sdp,
        headers: {
          Authorization: `Bearer ${session.client_secret}`,
          "Content-Type": "application/sdp",
        },
      });
      if (!sdpResponse.ok) {
        throw new Error(`OpenAI Realtime respondeu com status ${sdpResponse.status}.`);
      }
      await peer.setRemoteDescription({
        type: "answer",
        sdp: await sdpResponse.text(),
      });
      naturalVoiceTimerRef.current = setTimeout(() => {
        if (!naturalVoiceActiveRef.current) return;
        stopNaturalVoice();
        setVoiceError("A sessão de voz chegou ao limite de duração. Inicie outra para continuar.");
      }, session.max_duration_seconds * 1000);
    } catch (caught) {
      releaseNaturalVoiceResources();
      setNaturalVoicePhase("ERROR");
      if (caught instanceof DOMException && caught.name === "NotAllowedError") {
        setVoiceError("O acesso ao microfone foi negado. Autorize-o no navegador e tente novamente.");
      } else {
        setVoiceError(caught instanceof Error
          ? caught.message
          : "Não foi possível iniciar a conversa por voz.");
      }
    }
  }

  async function handleRealtimeEvent(rawEvent: string) {
    let event: RealtimeServerEvent;
    try {
      event = JSON.parse(rawEvent) as RealtimeServerEvent;
    } catch {
      return;
    }
    if (!naturalVoiceActiveRef.current) return;

    if (event.type === "input_audio_buffer.speech_started" && !toolRunningRef.current) {
      setNaturalVoicePhase("USER_SPEAKING");
      return;
    }
    if (event.type === "input_audio_buffer.speech_stopped" && !toolRunningRef.current) {
      setNaturalVoicePhase("PROCESSING");
      return;
    }
    if (event.type === "response.output_audio.delta" || event.type === "response.audio.delta") {
      setNaturalVoicePhase("RESPONDING");
      return;
    }
    if (event.type === "error") {
      setVoiceError(event.error?.message
        ? `A voz em tempo real informou: ${event.error.message}`
        : "A voz em tempo real encontrou um erro.");
      return;
    }
    if (event.type !== "response.done") return;

    const calls = (event.response?.output ?? []).filter(
      (item) => item.type === "function_call" && item.name === "submit_to_judge_cycle",
    );
    if (calls.length) {
      for (const call of calls) void runJudgeCycleFromVoice(call);
      return;
    }
    if (!toolRunningRef.current && event.response?.status !== "cancelled") {
      setNaturalVoicePhase("LISTENING");
    }
  }

  async function runJudgeCycleFromVoice(call: RealtimeFunctionCall) {
    if (!call.call_id || handledCallIdsRef.current.has(call.call_id) || toolRunningRef.current) return;
    handledCallIdsRef.current.add(call.call_id);
    let message = "";
    try {
      const argumentsValue = JSON.parse(call.arguments ?? "{}") as { message?: unknown };
      message = typeof argumentsValue.message === "string" ? argumentsValue.message.trim() : "";
    } catch {
      message = "";
    }
    if (!message) {
      sendFunctionOutput(call.call_id, {
        error: "Não foi possível compreender a fala. Peça ao usuário que repita.",
      });
      requestSpokenReply("Diga que não foi possível compreender e peça para a pessoa repetir com calma.");
      return;
    }

    toolRunningRef.current = true;
    setNaturalVoicePhase("ANALYZING");
    setVoiceError(null);
    setMicrophoneEnabled(false);
    try {
      const turn = await onSend(message.slice(0, 20_000), "VOICE");
      if (!naturalVoiceActiveRef.current) return;
      sendFunctionOutput(call.call_id, {
        status: turn.status,
        judge_response: turn.judge_response,
        decision: turn.decision,
        score: turn.score,
        confidence: turn.confidence,
      });
      setMicrophoneEnabled(true);
      setNaturalVoicePhase("RESPONDING");
      requestSpokenReply(
        "Responda em português brasileiro, de modo caloroso e natural. Use somente o resultado oficial da ferramenta. Preserve exatamente decisão, score e confiança; resuma o motivo e o próximo passo em até quatro frases. Não leia nomes de campos nem JSON.",
      );
    } catch (caught) {
      if (!naturalVoiceActiveRef.current) return;
      const messageText = caught instanceof Error
        ? caught.message
        : "O ciclo dos agentes não pôde ser concluído.";
      sendFunctionOutput(call.call_id, { error: messageText });
      setMicrophoneEnabled(true);
      setNaturalVoicePhase("RESPONDING");
      requestSpokenReply(
        "Explique brevemente, em português brasileiro, que o ciclo não pôde ser concluído. Não invente decisão, score ou confiança. Oriente a pessoa a corrigir o bloqueio mostrado na tela e tentar novamente.",
      );
    } finally {
      toolRunningRef.current = false;
      if (naturalVoiceActiveRef.current) setMicrophoneEnabled(true);
    }
  }

  function sendFunctionOutput(callId: string, output: object) {
    sendRealtimeEvent({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: callId,
        output: JSON.stringify(output),
      },
    });
  }

  function requestSpokenReply(instructions: string) {
    sendRealtimeEvent({
      type: "response.create",
      response: {
        output_modalities: ["audio"],
        tool_choice: "none",
        instructions,
      },
    });
  }

  function sendRealtimeEvent(event: object) {
    const channel = dataChannelRef.current;
    if (channel?.readyState === "open") channel.send(JSON.stringify(event));
  }

  function setMicrophoneEnabled(enabled: boolean) {
    microphoneStreamRef.current?.getAudioTracks().forEach((track) => {
      track.enabled = enabled;
    });
  }

  function stopListening() {
    shouldListenRef.current = false;
    if (restartTimerRef.current) {
      clearTimeout(restartTimerRef.current);
      restartTimerRef.current = null;
    }
    recognitionRef.current?.stop();
    setListening(false);
    setInterimTranscript("");
  }

  function toggleListening() {
    if (listening) {
      stopListening();
      return;
    }
    const Recognition = speechRecognitionConstructor();
    if (!Recognition) {
      setVoiceError("Este navegador não oferece transcrição de voz. Você ainda pode digitar normalmente.");
      return;
    }
    const recognition = new Recognition();
    recognition.lang = "pt-BR";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let finalized = "";
      let interim = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const transcript = result?.[0]?.transcript?.trim();
        if (!transcript) continue;
        if (result.isFinal) finalized += `${transcript} `;
        else interim += `${transcript} `;
      }
      if (finalized.trim()) {
        setDraft((current) => current.trim()
          ? `${current.trim()} ${finalized.trim()}`
          : finalized.trim());
        setVoiceCaptured(true);
      }
      setInterimTranscript(interim.trim());
    };
    recognition.onerror = (event) => {
      if (event.error === "no-speech" || event.error === "aborted") return;
      shouldListenRef.current = false;
      setListening(false);
      setInterimTranscript("");
      setVoiceError(event.error === "not-allowed" || event.error === "service-not-allowed"
        ? "O acesso ao microfone foi negado. Autorize o microfone no navegador e tente novamente."
        : "A escuta foi interrompida. Verifique o microfone e tente novamente.");
    };
    recognition.onend = () => {
      setInterimTranscript("");
      if (!shouldListenRef.current) {
        setListening(false);
        return;
      }
      restartTimerRef.current = setTimeout(() => {
        if (!shouldListenRef.current) return;
        try {
          recognition.start();
        } catch {
          shouldListenRef.current = false;
          setListening(false);
          setVoiceError("O navegador encerrou o reconhecimento. Clique no microfone para tentar novamente.");
        }
      }, 250);
    };
    recognitionRef.current = recognition;
    shouldListenRef.current = true;
    setVoiceError(null);
    setInterimTranscript("");
    setListening(true);
    try {
      recognition.start();
    } catch {
      shouldListenRef.current = false;
      setListening(false);
      setVoiceError("Não foi possível iniciar o microfone. Recarregue a página e tente novamente.");
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (listening) {
      stopListening();
      setVoiceError("A escuta foi encerrada. Confira a transcrição e envie novamente.");
      return;
    }
    const message = draft.trim();
    if (!message || disabled || submitting || naturalVoiceActive) return;
    setSubmitting(true);
    setVoiceError(null);
    try {
      const turn = await onSend(message, voiceCaptured ? "VOICE" : "TEXT");
      setDraft("");
      setVoiceCaptured(false);
      if (speakReplies && turn.judge_response && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(turn.judge_response);
        utterance.lang = "pt-BR";
        utterance.rate = 0.96;
        utterance.pitch = 1.02;
        const preferredVoice = window.speechSynthesis.getVoices().find(
          (voice) => voice.lang.toLowerCase() === "pt-br",
        );
        if (preferredVoice) utterance.voice = preferredVoice;
        window.speechSynthesis.speak(utterance);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="panel judge-chat-panel">
      <header>
        <h2>Converse com o Judge</h2>
        <span>1 ciclo completo por fala</span>
      </header>
      <div className="panel-body judge-chat-body">
        <div className="judge-chat-intro">
          <div>
            <p className="eyebrow">Conversa natural ou texto</p>
            <p>Sua fala passa por Researcher, Builder, Critic e Judge. O modo natural mantém o microfone aberto, entende suas pausas e permite interromper a resposta do Judge.</p>
          </div>
          {!naturalVoiceActive && (
            <label className="voice-reply-toggle">
              <input
                checked={speakReplies}
                onChange={(event) => setSpeakReplies(event.target.checked)}
                type="checkbox"
              />
              Ler respostas do modo texto
            </label>
          )}
        </div>

        <div className={`natural-voice-card natural-voice-${naturalVoicePhase.toLowerCase()}`}>
          <div className="natural-voice-status">
            <span className="natural-voice-orb" aria-hidden="true" />
            <div>
              <strong>{naturalVoiceLabel(naturalVoicePhase)}</strong>
              <small>
                {naturalVoiceActive
                  ? naturalVoiceHelp(naturalVoicePhase)
                  : "Voz neural pela Realtime API; sua chave padrão permanece protegida no backend."}
              </small>
            </div>
          </div>
          {naturalVoiceActive ? (
            <button className="button button-danger" onClick={stopNaturalVoice} type="button">
              Encerrar conversa
            </button>
          ) : (
            <button
              className="button"
              disabled={disabled || !naturalVoiceSupported}
              onClick={() => void startNaturalVoice()}
              type="button"
            >
              {naturalVoicePhase === "ERROR" ? "Tentar novamente" : "Iniciar conversa natural"}
            </button>
          )}
          <p className="natural-voice-meta">
            {naturalVoiceModel && naturalVoiceName
              ? `${naturalVoiceModel} · voz ${naturalVoiceName}`
              : "A voz natural gera custo adicional de áudio na API OpenAI; cada fala também executa o ciclo normal dos agentes."}
          </p>
        </div>

        <div className="judge-chat-history" aria-live="polite">
          {turns.length === 0 ? (
            <div className="judge-chat-empty">
              <strong>Comece com uma pergunta ou informação nova.</strong>
              <span>No modo natural, basta falar e aguardar. A pausa é detectada automaticamente.</span>
            </div>
          ) : turns.map((turn) => (
            <article className="judge-chat-exchange" key={turn.id}>
              <div className="chat-bubble chat-user">
                <span>Você · {turn.input_mode === "VOICE" ? "voz" : "texto"}</span>
                <p>{turn.user_message}</p>
              </div>
              <div className={`chat-bubble chat-judge chat-status-${turn.status.toLowerCase()}`}>
                <span>Judge · {judgeStatusLabel(turn.status)}</span>
                <p>{turn.judge_response ?? turn.error ?? "Processando o ciclo…"}</p>
                {turn.decision && (
                  <small>
                    {turn.decision} · score {turn.score ?? "—"}/100 · {formatConfidence(turn.confidence)} · custo desta conversa {formatCost(String(Math.max(0, Number(turn.cost_after) - Number(turn.cost_before))))}
                  </small>
                )}
              </div>
            </article>
          ))}
        </div>

        <form className="judge-chat-composer" onSubmit={submit}>
          <p className="eyebrow">Modo compatível: digitar ou transcrever</p>
          <textarea
            disabled={disabled || submitting || naturalVoiceActive}
            maxLength={20000}
            onChange={(event) => {
              setDraft(event.target.value);
              if (!event.target.value) setVoiceCaptured(false);
            }}
            placeholder="Ex.: Considere também clientes do setor público. Isso muda sua avaliação?"
            rows={3}
            value={draft}
          />
          <div className="judge-chat-controls">
            <button
              aria-pressed={listening}
              className={`button button-secondary microphone-button${listening ? " listening" : ""}`}
              disabled={disabled || submitting || naturalVoiceActive || !speechSupported}
              onClick={toggleListening}
              title={speechSupported ? "Transcrever pelo microfone" : "Voz indisponível neste navegador"}
              type="button"
            >
              {listening ? "Ouvindo… clique para parar" : "Usar microfone para transcrever"}
            </button>
            <small>{draft.length.toLocaleString("pt-BR")} / 20.000</small>
            <button className="button" disabled={disabled || submitting || listening || naturalVoiceActive || !draft.trim()} type="submit">
              {submitting ? "Executando o ciclo…" : listening ? "Pare o microfone para enviar" : "Enviar e executar 1 rodada"}
            </button>
          </div>
          {listening && (
            <p className="judge-chat-listening" role="status">
              <span aria-hidden="true" />
              {interimTranscript ? `Ouvindo: ${interimTranscript}` : "Microfone ativo — fale normalmente e clique em parar quando terminar."}
            </p>
          )}
          {voiceError && <p className="judge-chat-error">{voiceError}</p>}
          {blockReason && <p className="judge-chat-blocked">{blockReason}</p>}
        </form>
      </div>
    </section>
  );
}

function naturalVoiceLabel(phase: NaturalVoicePhase): string {
  return {
    IDLE: "Conversa por voz natural",
    CONNECTING: "Conectando a voz…",
    LISTENING: "Estou ouvindo",
    USER_SPEAKING: "Ouvindo você…",
    PROCESSING: "Entendendo sua fala…",
    ANALYZING: "Os agentes estão analisando…",
    RESPONDING: "O Judge está respondendo",
    ERROR: "A conversa foi desconectada",
  }[phase];
}

function naturalVoiceHelp(phase: NaturalVoicePhase): string {
  return {
    IDLE: "",
    CONNECTING: "Autorize o microfone quando o navegador solicitar.",
    LISTENING: "Fale normalmente; você não precisa apertar enviar.",
    USER_SPEAKING: "Pode fazer pausas — o sistema espera você concluir.",
    PROCESSING: "Preparando sua fala para o ciclo completo.",
    ANALYZING: "O microfone fica pausado enquanto o ciclo é executado.",
    RESPONDING: "Você pode interromper falando a qualquer momento.",
    ERROR: "",
  }[phase];
}

function judgeStatusLabel(status: JudgeChatTurn["status"]): string {
  return {
    RUNNING: "processando",
    COMPLETED: "respondido",
    NO_DECISION: "sem nova decisão",
    CANCELLED: "interrompido",
    BUDGET_STOPPED: "orçamento encerrado",
    FAILED: "falha",
  }[status];
}
