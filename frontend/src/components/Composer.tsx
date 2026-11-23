import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

interface Props {
  disabled: boolean;
  busy: boolean;
  placeholder: string;
  onSubmit: (q: string) => void;
  onStop: () => void;
  prefill?: { text: string; n: number };
}

export function Composer({ disabled, busy, placeholder, onSubmit, onStop, prefill }: Props) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (prefill) {
      setText(prefill.text);
      ref.current?.focus();
    }
  }, [prefill]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [text]);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const q = text.trim();
    if (!q || disabled || busy) return;
    onSubmit(q);
    setText("");
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form className="composer" onSubmit={submit}>
      <label htmlFor="question" className="sr-only">
        Ask a question about your data
      </label>
      <textarea
        id="question"
        ref={ref}
        rows={1}
        value={text}
        maxLength={2000}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
      />
      {busy ? (
        <button type="button" className="btn" onClick={onStop}>
          Stop
        </button>
      ) : (
        <button className="btn btn-primary" disabled={disabled || !text.trim()}>
          Ask
        </button>
      )}
    </form>
  );
}
