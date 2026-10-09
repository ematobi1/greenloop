"use client";

import { useEffect, useState } from "react";

// Updates once a minute; rendered empty on the server so hydration never mismatches.
export default function Clock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    const tick = () => setNow(new Date());
    const first = setTimeout(tick, 0);
    const timer = setInterval(tick, 30_000);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, []);
  if (!now) return <span className="hud-clock" />;
  return (
    <time className="hud-clock" dateTime={now.toISOString()}>
      {now.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}{" "}
      {now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
    </time>
  );
}
