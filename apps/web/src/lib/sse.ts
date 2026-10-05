// Incremental parser for a text/event-stream body (the subset the orchestrator sends:
// `event:` and `data:` lines, blank-line separated). Chunks may split anywhere,
// including inside a line or between \r and \n.

export type SseEvent = { event: string; data: string };

export function createSseParser(onEvent: (event: SseEvent) => void) {
  let buffer = "";
  let eventName = "";
  let dataLines: string[] = [];

  function dispatch() {
    if (dataLines.length > 0) onEvent({ event: eventName || "message", data: dataLines.join("\n") });
    eventName = "";
    dataLines = [];
  }

  function line(text: string) {
    if (text === "") return dispatch();
    if (text.startsWith(":")) return;
    const colon = text.indexOf(":");
    const field = colon === -1 ? text : text.slice(0, colon);
    let value = colon === -1 ? "" : text.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") eventName = value;
    else if (field === "data") dataLines.push(value);
  }

  return {
    push(chunk: string) {
      buffer += chunk;
      let match: RegExpExecArray | null;
      const lineEnd = /\r\n|\r|\n/g;
      let start = 0;
      while ((match = lineEnd.exec(buffer)) !== null) {
        // A lone \r at the very end may be the first half of \r\n: wait for more.
        if (match[0] === "\r" && match.index === buffer.length - 1) break;
        line(buffer.slice(start, match.index));
        start = match.index + match[0].length;
      }
      buffer = buffer.slice(start);
    },
    end() {
      if (buffer !== "") line(buffer.replace(/\r$/, ""));
      buffer = "";
      dispatch();
    },
  };
}
