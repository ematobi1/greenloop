"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  CORE_COLOURS,
  FRAME_BUDGET_MS,
  GLOBE_NODES,
  LEVEL_COLOURS,
  NARROW_QUERY,
  coreIntensity,
  nodeLevel,
  nodeStatusText,
  renderMode,
  type CoreState,
  type NodeLevel,
} from "@/lib/globe";
import type { Health } from "@/lib/hud";

type Mode = "loading" | "ready" | "fallback";

const ORBIT_RADIUS = 1.65;
const LABEL_MARGIN = 64;
const TILT = 0.38;

function orbitPosition(index: number, angle: number): [number, number, number] {
  const theta = angle + (index / GLOBE_NODES.length) * Math.PI * 2;
  const x = Math.cos(theta) * ORBIT_RADIUS;
  const z = Math.sin(theta) * ORBIT_RADIUS;
  return [x, z * Math.sin(TILT), z * Math.cos(TILT)];
}

// Labels for the static fallback: the same orbit, flattened onto the panel.
function fallbackPosition(index: number): { left: string; top: string } {
  const [x, y] = orbitPosition(index, 0.6);
  return { left: `${50 + x * 26}%`, top: `${48 - y * 40 - (index % 2 ? 6 : -6)}%` };
}

// The HUD's holographic globe (ADR 0014). three.js is loaded only here, on demand. Labels
// are DOM buttons over the canvas, so they stay text (screen readers, a future strict CSP).
export default function HudGlobe({
  coreState,
  deltaTick,
  health,
}: {
  coreState: CoreState;
  deltaTick: number;
  health: Health | null;
}) {
  const container = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const labels = useRef<(HTMLButtonElement | null)[]>([]);
  const live = useRef({ coreState, levels: [] as NodeLevel[], burst: 0, redraw: () => undefined as void });
  const [mode, setMode] = useState<Mode>("loading");
  const [motion, setMotion] = useState<"animate" | "still" | "paused">("still");
  const [selected, setSelected] = useState<string | null>(null);

  const levels = useMemo(() => GLOBE_NODES.map((node) => nodeLevel(node, health)), [health]);
  const selectedIndex = GLOBE_NODES.findIndex((node) => node.id === selected);

  useEffect(() => {
    live.current.coreState = coreState;
    live.current.levels = levels;
    live.current.redraw();
  }, [coreState, levels]);

  useEffect(() => {
    live.current.burst = 1;
    live.current.redraw();
  }, [deltaTick]);

  useEffect(() => {
    let disposed = false;
    let teardown = () => undefined as void;
    import("three")
      .then((THREE) => {
        if (disposed || !container.current || !canvas.current) return;
        try {
          teardown = mountGlobe(THREE, container.current, canvas.current, labels, live, setMotion);
          setMode("ready");
        } catch {
          setMode("fallback");
        }
      })
      .catch(() => !disposed && setMode("fallback"));
    return () => {
      disposed = true;
      teardown();
    };
  }, []);

  return (
    <div
      ref={container}
      className={`hud-globe hud-globe--${mode}`}
      data-globe={mode}
      data-motion={motion}
      data-core-state={coreState}
    >
      <canvas ref={canvas} className="hud-globe__canvas" aria-hidden="true" />
      {mode !== "ready" && <div className="hud-globe__still" aria-hidden="true" />}
      <ul className="hud-globe__nodes" aria-label="System map">
        {GLOBE_NODES.map((node, index) => {
          const level = levels[index];
          const text = nodeStatusText(node, level);
          return (
            <li key={node.id}>
              <button
                type="button"
                ref={(element) => {
                  labels.current[index] = element;
                }}
                className={`hud-node hud-node--${level}`}
                style={mode === "ready" ? undefined : fallbackPosition(index)}
                aria-label={text}
                aria-pressed={selected === node.id}
                onClick={() => setSelected((current) => (current === node.id ? null : node.id))}
              >
                <span className="hud-node__dot" aria-hidden="true" />
                <span className="hud-node__label">{node.label}</span>
                <span className="hud-node__basis">{node.basis}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="hud-globe__detail" role="status">
        {selectedIndex >= 0 ? nodeStatusText(GLOBE_NODES[selectedIndex], levels[selectedIndex]) : ""}
      </p>
    </div>
  );
}

type Three = typeof import("three");
type Live = React.RefObject<{ coreState: CoreState; levels: NodeLevel[]; burst: number; redraw: () => void }>;

function mountGlobe(
  THREE: Three,
  container: HTMLDivElement,
  canvas: HTMLCanvasElement,
  labels: React.RefObject<(HTMLButtonElement | null)[]>,
  live: Live,
  setMotion: (mode: "animate" | "still" | "paused") => void,
): () => void {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 50);
  camera.position.set(0, 0.55, 6.2);
  camera.lookAt(0, -0.1, 0);

  const disposables: { dispose: () => void }[] = [];
  const track = <T extends { dispose: () => void }>(item: T): T => {
    disposables.push(item);
    return item;
  };
  const additive = (colour: number, opacity: number, side: import("three").Side = THREE.FrontSide) =>
    track(new THREE.MeshBasicMaterial({ color: colour, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false, side }));

  const globe = new THREE.Group();
  scene.add(globe);
  const sphere = track(new THREE.IcosahedronGeometry(1, 4));
  globe.add(
    new THREE.LineSegments(
      track(new THREE.WireframeGeometry(sphere)),
      track(new THREE.LineBasicMaterial({ color: 0x3dd6ff, transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending, depthWrite: false })),
    ),
  );
  globe.add(new THREE.Points(sphere, track(new THREE.PointsMaterial({ color: 0x9ff0ff, size: 0.025, transparent: true, opacity: 0.8 }))));
  const coreMaterial = additive(CORE_COLOURS.idle, 0.28);
  const core = new THREE.Mesh(track(new THREE.SphereGeometry(0.78, 32, 32)), coreMaterial);
  scene.add(core);
  scene.add(new THREE.Mesh(track(new THREE.SphereGeometry(1.18, 32, 32)), additive(0x3dd6ff, 0.08, THREE.BackSide)));

  const platform = new THREE.Group();
  platform.position.y = -1.45;
  platform.rotation.x = -Math.PI / 2;
  [1.2, 1.6, 2.05].forEach((radius, index) => {
    platform.add(new THREE.Mesh(track(new THREE.RingGeometry(radius - 0.02, radius, 96)), additive(0x3dd6ff, 0.45 - index * 0.1)));
  });
  scene.add(platform);

  const orbit = new THREE.Mesh(track(new THREE.TorusGeometry(ORBIT_RADIUS, 0.004, 8, 160)), additive(0x6f8bff, 0.35));
  orbit.rotation.x = Math.PI / 2 - TILT;
  scene.add(orbit);

  const nodeGeometry = track(new THREE.SphereGeometry(0.06, 16, 16));
  const nodes = GLOBE_NODES.map(() => {
    const material = track(new THREE.MeshBasicMaterial({ color: LEVEL_COLOURS.unknown }));
    const mesh = new THREE.Mesh(nodeGeometry, material);
    scene.add(mesh);
    return { mesh, material };
  });

  const projected = new THREE.Vector3();
  let width = 1;
  let height = 1;
  let angle = 0;
  let drag: { x: number; rotation: number } | null = null;
  let frame = 0;
  let frames = 0;
  let last = 0;

  const draw = (time: number) => {
    const state = live.current.coreState;
    coreMaterial.color.setHex(CORE_COLOURS[state]);
    coreMaterial.opacity = 0.18 * coreIntensity(state, time / 1000, live.current.burst);
    core.scale.setScalar(1 + 0.04 * live.current.burst);
    nodes.forEach(({ mesh, material }, index) => {
      material.color.setHex(LEVEL_COLOURS[live.current.levels[index] ?? "unknown"]);
      mesh.position.set(...orbitPosition(index, angle));
      projected.copy(mesh.position).project(camera);
      const label = labels.current[index];
      if (label) {
        // Keep labels inside the panel on narrow screens.
        const x = Math.min(Math.max(((projected.x + 1) / 2) * width, LABEL_MARGIN), width - LABEL_MARGIN);
        const y = ((1 - projected.y) / 2) * height;
        label.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
      }
    });
    renderer.render(scene, camera);
    frames += 1;
    if (frames % 10 === 1) container.dataset.frames = String(frames);
  };

  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const narrowQuery = window.matchMedia(NARROW_QUERY);
  const mode = () =>
    renderMode({ reducedMotion: motionQuery.matches, hidden: document.hidden, narrow: narrowQuery.matches });

  const tick = (time: number) => {
    frame = requestAnimationFrame(tick);
    if (time - last < FRAME_BUDGET_MS) return;
    const delta = last ? (time - last) / 1000 : 0;
    last = time;
    if (!drag) {
      globe.rotation.y += delta * 0.12;
      angle += delta * 0.18;
    }
    live.current.burst = Math.max(0, live.current.burst - delta * 2.5);
    draw(time);
  };

  const apply = () => {
    const current = mode();
    setMotion(current);
    cancelAnimationFrame(frame);
    frame = 0;
    last = 0;
    if (current === "animate") frame = requestAnimationFrame(tick);
    else if (current === "still") draw(0);
  };

  const resize = () => {
    width = container.clientWidth;
    height = container.clientHeight;
    renderer.setSize(width, height, false);
    camera.aspect = width / Math.max(height, 1);
    camera.updateProjectionMatrix();
    if (mode() === "still") draw(0);
  };
  const observer = new ResizeObserver(resize);
  observer.observe(container);
  resize();

  // A still globe redraws on demand: new health colours, a new core state, a drag.
  live.current.redraw = () => {
    if (mode() === "still") draw(0);
  };

  const down = (event: PointerEvent) => {
    drag = { x: event.clientX, rotation: globe.rotation.y };
  };
  const move = (event: PointerEvent) => {
    if (!drag) return;
    globe.rotation.y = drag.rotation + (event.clientX - drag.x) * 0.01;
    if (mode() === "still") draw(0);
  };
  const up = () => {
    drag = null;
  };
  canvas.addEventListener("pointerdown", down);
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
  document.addEventListener("visibilitychange", apply);
  motionQuery.addEventListener("change", apply);
  narrowQuery.addEventListener("change", apply);
  apply();

  return () => {
    cancelAnimationFrame(frame);
    observer.disconnect();
    canvas.removeEventListener("pointerdown", down);
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    document.removeEventListener("visibilitychange", apply);
    motionQuery.removeEventListener("change", apply);
    narrowQuery.removeEventListener("change", apply);
    live.current.redraw = () => undefined;
    disposables.forEach((item) => item.dispose());
    renderer.dispose();
  };
}
