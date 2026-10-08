import Link from "next/link";

import Clock from "./Clock";
import { HudDataProvider } from "./HudData";
import GreenLoopMark from "./GreenLoopMark";
import { Rail, Tabs } from "./Nav";
import StatusPill from "./StatusPill";
import UserMenu from "./UserMenu";

// The HUD frame around every signed-in page: top bar (brand, tabs, status, clock, user)
// and the left icon rail. Pages render inside <main>.
export default function Shell({ children }: { children: React.ReactNode }) {
  return (
    <HudDataProvider>
    <div className="hud-shell">
      <header className="hud-topbar">
        <Link href="/chat" className="hud-brand">
          <GreenLoopMark />
          <span>
            <span className="hud-brand__name">GreenLoop</span>
            <span className="hud-brand__tagline">Your second brain</span>
          </span>
        </Link>
        <Tabs />
        <div className="hud-status">
          <StatusPill />
          <Clock />
          <UserMenu />
        </div>
      </header>
      <div className="hud-body">
        <Rail />
        <main className="hud-main" id="main">
          {children}
        </main>
      </div>
    </div>
    </HudDataProvider>
  );
}
