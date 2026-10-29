import { Component, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Edges, Float, Grid, Line, OrbitControls, Sparkles, Stars } from '@react-three/drei';
import { AdditiveBlending, Object3D, QuadraticBezierCurve3, Vector3 } from 'three';

const BLUE = '#38bdf8';
const PURPLE = '#a855f7';
const ICE = '#e0f2fe';
const STEEL = '#0a0f1a';

// One pass through the pipeline, in seconds. Every timing below is a point
// inside this loop.
const CYCLE = 12;

// What a viewer who asked for reduced motion sees: the answer has formed,
// the chunks sit in the store.
const STILL_FRAME = 10.6;

const STAGES = [
  { start: 0, label: 'Upload' },
  { start: 1.8, label: 'API Gateway' },
  { start: 3.4, label: 'Chunk & embed' },
  { start: 4.3, label: 'ChromaDB' },
  { start: 6.1, label: 'Retrieve' },
  { start: 6.9, label: 'Ollama LLM' },
  { start: 8.4, label: 'Answer' },
];

// ---- Layout -----------------------------------------------------------------
// Left to right: the document enters through the API gateway, the
// orchestrator splits it, the silo stores it, the neural core answers.

const FLOOR_Y = -2.05;

const API_X = -3;
const API_Y = 0;
const API_RADIUS = 0.5;

const DOC_SCALE = 0.8;
const DOC_TOP = 4.3;
const DOC_REST = 1.5;
const DOC_WIDTH = 1.1;
const DOC_HEIGHT = 1.4;

const ORCH_X = -0.7;
const ORCH_Y = 0.5;

const SILO_X = 0.6;
const SILO_Y = -1.15;
const SILO_SCALE = 0.85;
const CYL_HEIGHT = 1.6;
const CYL_RADIUS = 0.75;
const SILO_TOP = SILO_Y + (CYL_HEIGHT / 2) * SILO_SCALE + 0.12;
const SILO_RINGS = [-0.6, -0.3, 0, 0.3, 0.6];
const SILO_STRUTS = 8;

const BRAIN_X = 2.9;
const BRAIN_Y = 0.45;
const BRAIN_SCALE = 0.85;
const ANSWER_TOP = 1.95;
const ANSWER_WIDTH = 1.3;
const ANSWER_HEIGHT = 0.7;

// The local machine: everything above sits inside this box.
const BOX_LEFT = -3.9;
const BOX_RIGHT = 4.1;
const BOX_TOP = 2.55;
const BOX_DEPTH = 3;
const BOX_WIDTH = BOX_RIGHT - BOX_LEFT;
const BOX_HEIGHT = BOX_TOP - FLOOR_Y;
const BOX_CENTER = [(BOX_LEFT + BOX_RIGHT) / 2, (BOX_TOP + FLOOR_Y) / 2, 0];

const CUBE_OFFSETS = [
  [-0.4, -0.6],
  [0, -0.75],
  [0.4, -0.6],
];
const CUBE_SLOTS = [-0.45, 0, 0.45];
const DOC_LINES = [0.3, 0.14, -0.02, -0.18, -0.34];
const ANSWER_LINES = [0.95, 0.8, 0.55];
const PULSE_TRAIL = 5;

// Everything spans about 8.2 units; below this aspect ratio the scene is
// scaled down to stay in frame rather than cropped.
const FIT_ASPECT = 1.25;

const v = (x, y, z = 0) => new Vector3(x, y, z);

const CURVES = {
  intake: new QuadraticBezierCurve3(v(API_X, BOX_TOP), v(API_X, 1.3), v(API_X, API_Y)),
  api: new QuadraticBezierCurve3(v(API_X, API_Y), v(-1.85, 0.9, 0.3), v(ORCH_X, ORCH_Y)),
  store: new QuadraticBezierCurve3(v(ORCH_X, ORCH_Y), v(0.55, 0.7, 0.3), v(SILO_X, SILO_TOP)),
  llm: new QuadraticBezierCurve3(v(ORCH_X, ORCH_Y), v(1.1, 1.9, 0.3), v(BRAIN_X, BRAIN_Y)),
};

const clamp01 = (x) => Math.min(Math.max(x, 0), 1);
const lerp = (a, b, p) => a + (b - a) * p;
const ease = (p) => p * p * (3 - 2 * p);
const progress = (t, start, end) => clamp01((t - start) / (end - start));

// Rises from start to peak, falls back to zero by end.
const envelope = (t, start, peak, end) => {
  if (t <= start || t >= end) return 0;
  if (t < peak) return ease((t - start) / (peak - start));
  return 1 - ease((t - peak) / (end - peak));
};

// Always-on trickles along each link, each surging when its step runs.
const STREAMS = [
  { curve: CURVES.intake, count: 6, speed: 0.25, burst: (t) => envelope(t, 0.2, 1, 2.4) },
  { curve: CURVES.api, count: 8, speed: 0.15, burst: (t) => envelope(t, 2.2, 2.9, 3.8) },
  {
    curve: CURVES.store,
    count: 8,
    speed: 0.15,
    burst: (t) => Math.max(envelope(t, 4.2, 4.9, 5.8), envelope(t, 6, 6.5, 7)),
  },
  { curve: CURVES.llm, count: 10, speed: 0.12, burst: (t) => envelope(t, 6.8, 7.3, 8.2) },
];
const STREAM_TOTAL = STREAMS.reduce((sum, stream) => sum + stream.count, 0);

// The bright packet: the document into the orchestrator, then the retrieved
// context back out of the silo and on to the model.
const PULSES = [
  { curve: CURVES.api, start: 2.4, end: 3.4 },
  { curve: CURVES.store, start: 6.2, end: 6.9, reverse: true },
  { curve: CURVES.llm, start: 6.9, end: 7.8 },
];

const setScale = (object, s) => {
  object.visible = s > 0.001;
  object.scale.setScalar(Math.max(s, 0.001));
};

const stageAt = (t) => {
  let index = 0;
  STAGES.forEach((stage, i) => {
    if (t >= stage.start) index = i;
  });
  return index;
};

const useMediaQuery = (query) => {
  const [matches, setMatches] = useState(
    () => typeof window !== 'undefined' && window.matchMedia?.(query).matches,
  );

  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return undefined;

    const onChange = (event) => setMatches(event.matches);
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, [query]);

  return Boolean(matches);
};

function Neon({ color, intensity = 4, ...props }) {
  return (
    <meshStandardMaterial
      color={color}
      emissive={color}
      emissiveIntensity={intensity}
      toneMapped={false}
      {...props}
    />
  );
}

// Frosted glass. Transmission refracts the opaque scene behind it, so the
// chunks stay visible inside the silo.
function Glass(props) {
  return (
    <meshPhysicalMaterial
      transmission={1}
      roughness={0.2}
      thickness={2}
      ior={1.4}
      clearcoat={1}
      clearcoatRoughness={0.1}
      attenuationColor={BLUE}
      attenuationDistance={4}
      {...props}
    />
  );
}

// Four emissive bars around a panel: a glowing border that reads at any
// angle, which a one-pixel line does not.
function PanelFrame({ width, height, color, thickness = 0.025, intensity = 4 }) {
  const bars = [
    [0, height / 2, width + thickness, thickness],
    [0, -height / 2, width + thickness, thickness],
    [-width / 2, 0, thickness, height],
    [width / 2, 0, thickness, height],
  ];

  return bars.map(([x, y, w, h]) => (
    <mesh key={`${x}:${y}`} position={[x, y, 0.03]}>
      <boxGeometry args={[w, h, 0.02]} />
      <Neon color={color} intensity={intensity} />
    </mesh>
  ));
}

function Scene({ reducedMotion, stepRefs }) {
  const root = useRef();
  const plate = useRef();
  const doc = useRef();
  const docScan = useRef();
  const api = useRef();
  const apiCore = useRef();
  const apiRing = useRef();
  const orch = useRef();
  const orchShell = useRef();
  const orchCore = useRef();
  const orchCoreMaterial = useRef();
  const orchOrbit = useRef();
  const cubes = useRef([]);
  const silo = useRef();
  const siloRings = useRef([]);
  const siloRingMaterials = useRef([]);
  const siloCore = useRef();
  const stream = useRef();
  const streamOffsets = useRef(STREAMS.map(() => 0));
  const beams = useRef([]);
  const pulses = useRef([]);
  const brainCore = useRef();
  const brainMaterial = useRef();
  const brainHalo = useRef();
  const brainInner = useRef();
  const brainOuter = useRef();
  const brainOrbits = useRef();
  const brainLight = useRef();
  const answer = useRef();
  const answerLines = useRef([]);
  const lastStage = useRef(-1);

  const point = useMemo(() => new Vector3(), []);
  const dummy = useMemo(() => new Object3D(), []);
  const beamPoints = useMemo(() => STREAMS.map((s) => s.curve.getPoints(64)), []);

  const { width, height } = useThree((state) => state.size);
  const fit = Math.min(1, width / height / FIT_ASPECT);

  useFrame((state, delta) => {
    const time = state.clock.elapsedTime;
    const t = reducedMotion ? STILL_FRAME : time % CYCLE;
    // Idle motion; zero for reduced motion so the still frame stays still.
    const idle = reducedMotion ? 0 : 1;
    const breath = 0.5 + 0.5 * Math.sin(time * 1.8);
    const fade = 1 - ease(progress(t, 11.2, 11.8));

    root.current.rotation.y = Math.sin(time * 0.25) * 0.1 * idle;
    plate.current.opacity = 0.05 + breath * 0.03 * idle;

    // 1. The document drifts down and is taken in by the gateway.
    const fall = ease(progress(t, 0, 1.8));
    const intake = ease(progress(t, 1.8, 2.5));

    doc.current.position.y =
      lerp(lerp(DOC_TOP, DOC_REST, fall), API_Y, intake) +
      Math.sin(time * 1.2) * 0.05 * idle * (1 - intake);
    doc.current.rotation.z = (1 - fall) * 0.35;
    doc.current.rotation.y = (1 - fall) * 0.6 + Math.sin(time * 0.7) * 0.08 * idle;
    setScale(
      doc.current,
      DOC_SCALE * ease(progress(t, 0, 0.4)) * (1 - ease(progress(t, 1.9, 2.5))),
    );
    docScan.current.position.y = DOC_HEIGHT / 2 - 0.08 - ((time * 0.6) % 1) * (DOC_HEIGHT - 0.16);

    // 2. API gateway.
    const apiFlash = envelope(t, 1.9, 2.4, 3.4);

    api.current.position.y = API_Y + Math.sin(time * 1.1) * 0.04 * idle;
    apiCore.current.rotation.set(time * 0.8, time * 1.1, 0);
    apiRing.current.emissiveIntensity = 2.5 + breath * idle + apiFlash * 6;

    // 3. The orchestrator splits the document into embedded chunks, and
    //    later sends the retrieved ones on to the model.
    const orchFlash = Math.max(envelope(t, 3.2, 3.6, 4.6), envelope(t, 6.7, 7, 7.6));

    orch.current.position.y = ORCH_Y + Math.sin(time * 1.3) * 0.06 * idle;
    orchShell.current.rotation.y = time * 0.4 * idle;
    orchCore.current.rotation.set(time * 0.9, -time * 1.2, 0);
    orchCoreMaterial.current.emissiveIntensity = 3 + breath * idle + orchFlash * 8;
    orchOrbit.current.rotation.y = -time * 0.7;

    const split = ease(progress(t, 3.5, 4.1));

    cubes.current.forEach((cube, i) => {
      if (!cube) return;

      const travel = ease(progress(t, 4.3 + i * 0.2, 5.1 + i * 0.2));
      const settle = ease(progress(t, 5.1 + i * 0.2, 5.5 + i * 0.2));
      const [ox, oy] = CUBE_OFFSETS[i];

      CURVES.store.getPoint(travel, point);
      cube.position.set(
        point.x + ox * split * (1 - travel),
        lerp(point.y + oy * split * (1 - travel), SILO_Y + CUBE_SLOTS[i] * SILO_SCALE, settle) +
          Math.sin(time * 2 + i * 1.7) * 0.04 * settle * idle,
        point.z,
      );
      cube.rotation.x = time * 0.6 + i;
      cube.rotation.y = time * 0.9 + i * 2;
      setScale(cube, split * lerp(1, 0.55, travel) * fade);
    });

    // 4. The silo's rings run a slow wave, and flare as chunks land and as
    //    they are read back out.
    const siloFlash = Math.max(envelope(t, 5.2, 5.7, 6.6), envelope(t, 6, 6.2, 6.9) * 0.7);

    silo.current.rotation.y = time * 0.15 * idle;

    siloRings.current.forEach((ring, i) => {
      if (!ring) return;
      ring.rotation.z = time * (i % 2 ? -0.6 : 0.6) * idle + i;
    });

    siloRingMaterials.current.forEach((material, i) => {
      if (!material) return;
      const wave = 0.5 + 0.5 * Math.sin(time * 2.5 - i * 0.9);
      material.emissiveIntensity = 1.5 + wave * 2 * idle + siloFlash * 5;
    });

    siloCore.current.emissiveIntensity = 2 + siloFlash * 8;

    // Data streams along every link.
    const step = Math.min(delta, 0.1) * idle;
    let index = 0;

    STREAMS.forEach((s, k) => {
      const burst = s.burst(t);
      const offset = (streamOffsets.current[k] + step * (s.speed + burst * 0.5)) % 1;

      streamOffsets.current[k] = offset;

      for (let i = 0; i < s.count; i += 1) {
        const u = (i / s.count + offset) % 1;

        s.curve.getPoint(u, point);
        dummy.position.copy(point);
        dummy.rotation.set(time + i, time * 1.3 + i, 0);
        dummy.scale.setScalar(Math.max((0.5 + burst * 0.6) * Math.sin(u * Math.PI), 0.001));
        dummy.updateMatrix();
        stream.current.setMatrixAt(index, dummy.matrix);
        index += 1;
      }

      const beam = beams.current[k];
      if (beam) beam.material.opacity = 0.12 + burst * 0.5;
    });

    stream.current.instanceMatrix.needsUpdate = true;

    const pulse = PULSES.find((p) => t > p.start && t < p.end);

    pulses.current.forEach((mesh, k) => {
      if (!mesh) return;

      if (!pulse) {
        setScale(mesh, 0);
        return;
      }

      const along = clamp01(ease(progress(t, pulse.start, pulse.end)) - k * 0.05);

      pulse.curve.getPoint(pulse.reverse ? 1 - along : along, point);
      mesh.position.copy(point);
      setScale(mesh, 1 - k * 0.18);
    });

    // 5. The neural core lights up while it generates.
    const glow = envelope(t, 7.6, 8.1, 9.6);

    brainMaterial.current.emissiveIntensity = 4 + breath * 1.5 * idle + glow * 8;
    brainCore.current.scale.setScalar(1 + glow * 0.15);
    brainHalo.current.scale.setScalar(1 + breath * 0.08 * idle + glow * 0.35);
    brainInner.current.rotation.set(time * 0.25, time * 0.35, 0);
    brainOuter.current.rotation.set(-time * 0.12, -time * 0.18, time * 0.05);
    brainOrbits.current.rotation.y = time * 0.5;
    brainLight.current.intensity = 4 + glow * 20;

    // 6. The answer rises out of the core and writes itself.
    const rise = ease(progress(t, 8.4, 10.4));

    answer.current.position.y =
      lerp(BRAIN_Y, ANSWER_TOP, rise) + Math.sin(time * 1.5) * 0.04 * rise * idle;
    answer.current.rotation.y = Math.sin(time * 0.8) * 0.1 * idle;
    setScale(answer.current, 0.9 * ease(progress(t, 8.4, 8.9)) * fade);

    answerLines.current.forEach((line, i) => {
      if (!line) return;
      line.scale.x = Math.max(ease(progress(t, 9 + i * 0.35, 9.5 + i * 0.35)), 0.001);
    });

    // The step strip is plain DOM, updated only when the stage changes so
    // the animation never re-renders React.
    const stage = stageAt(t);

    if (stage !== lastStage.current) {
      lastStage.current = stage;
      stepRefs.current.forEach((stepEl, i) => {
        if (stepEl) stepEl.dataset.active = String(i === stage);
      });
    }
  });

  return (
    <group ref={root} position={[-0.1, -0.1, 0]} scale={fit}>
      {/* Floor */}
      <Grid
        position={[0, FLOOR_Y, 0]}
        args={[20, 20]}
        cellSize={0.4}
        cellThickness={0.6}
        cellColor="#0c3550"
        sectionSize={2}
        sectionThickness={1.1}
        sectionColor={BLUE}
        fadeDistance={14}
        fadeStrength={2}
        infiniteGrid
      />

      {/* The local machine boundary */}
      <mesh position={BOX_CENTER}>
        <boxGeometry args={[BOX_WIDTH, BOX_HEIGHT, BOX_DEPTH]} />
        <meshBasicMaterial visible={false} />
        <Edges color={BLUE} transparent opacity={0.35} />
      </mesh>
      <group position={[BOX_CENTER[0], FLOOR_Y + 0.01, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <mesh>
          <planeGeometry args={[BOX_WIDTH, BOX_DEPTH]} />
          <meshStandardMaterial
            ref={plate}
            color={BLUE}
            emissive={BLUE}
            emissiveIntensity={0.6}
            transparent
            opacity={0.06}
            depthWrite={false}
          />
        </mesh>
        <PanelFrame width={BOX_WIDTH} height={BOX_DEPTH} color={BLUE} thickness={0.03} intensity={2.5} />
      </group>

      {/* Document: a frosted tech panel */}
      <group ref={doc} position={[API_X, DOC_TOP, 0.1]} scale={DOC_SCALE}>
        <mesh>
          <boxGeometry args={[DOC_WIDTH, DOC_HEIGHT, 0.04]} />
          <Glass color="#bfe6ff" emissive="#0b2a4a" emissiveIntensity={0.6} />
        </mesh>
        <PanelFrame width={DOC_WIDTH} height={DOC_HEIGHT} color={BLUE} />
        <mesh position={[0, DOC_HEIGHT / 2 - 0.14, 0.03]}>
          <boxGeometry args={[DOC_WIDTH - 0.2, 0.08, 0.01]} />
          <Neon color={PURPLE} intensity={3} />
        </mesh>
        {DOC_LINES.map((y, i) => (
          <mesh key={y} position={[i === DOC_LINES.length - 1 ? -0.12 : 0, y, 0.03]}>
            <boxGeometry args={[i === DOC_LINES.length - 1 ? 0.46 : 0.7, 0.04, 0.01]} />
            <Neon color={ICE} intensity={2} />
          </mesh>
        ))}
        <mesh ref={docScan} position={[0, 0, 0.04]}>
          <boxGeometry args={[DOC_WIDTH - 0.06, 0.012, 0.005]} />
          <Neon color={BLUE} intensity={8} transparent opacity={0.8} />
        </mesh>
      </group>

      {/* API gateway: a hexagonal port */}
      <group ref={api} position={[API_X, API_Y, 0]}>
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[API_RADIUS, API_RADIUS, 0.22, 6]} />
          <Glass color="#d6f0ff" emissive="#06213a" emissiveIntensity={0.4} />
          <Edges color={BLUE} />
        </mesh>
        <mesh rotation={[0, 0, Math.PI / 2]}>
          <torusGeometry args={[API_RADIUS + 0.12, 0.022, 8, 6]} />
          <meshStandardMaterial
            ref={apiRing}
            color={BLUE}
            emissive={BLUE}
            emissiveIntensity={2.5}
            toneMapped={false}
          />
        </mesh>
        <mesh ref={apiCore}>
          <octahedronGeometry args={[0.16]} />
          <Neon color={ICE} intensity={5} />
        </mesh>
        <pointLight color={BLUE} intensity={2} distance={2.5} />
      </group>

      {/* RAG orchestrator: a floating prism */}
      <group ref={orch} position={[ORCH_X, ORCH_Y, 0]}>
        <group ref={orchShell}>
          <mesh position={[0, 0.2, 0]}>
            <coneGeometry args={[0.5, 0.75, 4]} />
            <Glass color="#ead8ff" emissive="#1a0b2e" emissiveIntensity={0.5} attenuationColor={PURPLE} />
            <Edges color={PURPLE} />
          </mesh>
          <mesh position={[0, -0.3, 0]} rotation={[Math.PI, 0, 0]}>
            <coneGeometry args={[0.5, 0.25, 4]} />
            <Neon color={PURPLE} intensity={2} wireframe transparent opacity={0.6} />
          </mesh>
        </group>
        <mesh ref={orchCore} position={[0, 0.05, 0]}>
          <tetrahedronGeometry args={[0.14]} />
          <meshStandardMaterial
            ref={orchCoreMaterial}
            color={ICE}
            emissive={PURPLE}
            emissiveIntensity={3}
            toneMapped={false}
          />
        </mesh>
        <group ref={orchOrbit}>
          <mesh rotation={[Math.PI / 2 + 0.25, 0, 0]}>
            <torusGeometry args={[0.72, 0.008, 8, 96]} />
            <Neon color={BLUE} intensity={3} />
          </mesh>
        </group>
        <pointLight color={PURPLE} intensity={3} distance={2.5} />
      </group>

      {/* Chunks / embeddings */}
      {CUBE_OFFSETS.map((_, i) => (
        <mesh
          key={i}
          ref={(el) => {
            cubes.current[i] = el;
          }}
          position={[ORCH_X, ORCH_Y, 0]}
          visible={false}
        >
          <boxGeometry args={[0.3, 0.3, 0.3]} />
          <meshStandardMaterial
            color="#0c1a2b"
            emissive={BLUE}
            emissiveIntensity={4}
            toneMapped={false}
          />
          <Edges color={ICE} />
        </mesh>
      ))}

      {/* Vector store: a data silo */}
      <group position={[SILO_X, SILO_Y, 0]} scale={SILO_SCALE}>
        <mesh>
          <cylinderGeometry args={[CYL_RADIUS, CYL_RADIUS, CYL_HEIGHT, 64]} />
          <Glass
            color="#e6f6ff"
            emissive="#06213a"
            emissiveIntensity={0.15}
            attenuationColor="#7cc8f0"
            attenuationDistance={10}
          />
        </mesh>

        {/* Base and cap, with glowing rims */}
        {[
          { y: -CYL_HEIGHT / 2 - 0.06, top: 0.92, bottom: 1.02, h: 0.18 },
          { y: CYL_HEIGHT / 2 + 0.05, top: 0.82, bottom: 0.92, h: 0.12 },
        ].map((part) => (
          <group key={part.y} position={[0, part.y, 0]}>
            <mesh>
              <cylinderGeometry args={[part.top, part.bottom, part.h, 64]} />
              <meshStandardMaterial color={STEEL} metalness={0.85} roughness={0.3} />
            </mesh>
            <mesh position={[0, part.h / 2, 0]} rotation={[Math.PI / 2, 0, 0]}>
              <torusGeometry args={[part.top, 0.018, 12, 96]} />
              <Neon color={BLUE} intensity={5} />
            </mesh>
          </group>
        ))}

        <group ref={silo}>
          {/* Struts around the shell */}
          {Array.from({ length: SILO_STRUTS }, (_, i) => {
            const angle = (i / SILO_STRUTS) * Math.PI * 2;
            return (
              <mesh
                key={i}
                position={[Math.cos(angle) * (CYL_RADIUS + 0.02), 0, Math.sin(angle) * (CYL_RADIUS + 0.02)]}
              >
                <boxGeometry args={[0.025, CYL_HEIGHT, 0.025]} />
                <Neon color={BLUE} intensity={1.2} />
              </mesh>
            );
          })}

          {/* Internal rings, each with a gap so their rotation reads */}
          {SILO_RINGS.map((y, i) => (
            <mesh
              key={y}
              ref={(el) => {
                siloRings.current[i] = el;
              }}
              position={[0, y, 0]}
              rotation={[Math.PI / 2, 0, 0]}
            >
              <torusGeometry args={[CYL_RADIUS - 0.13, 0.014, 10, 96, Math.PI * 1.6]} />
              <meshStandardMaterial
                ref={(el) => {
                  siloRingMaterials.current[i] = el;
                }}
                color={i % 2 ? PURPLE : BLUE}
                emissive={i % 2 ? PURPLE : BLUE}
                emissiveIntensity={2}
                toneMapped={false}
              />
            </mesh>
          ))}
        </group>

        {/* Light column through the middle */}
        <mesh>
          <cylinderGeometry args={[0.035, 0.035, CYL_HEIGHT, 12]} />
          <meshStandardMaterial
            ref={siloCore}
            color={ICE}
            emissive={BLUE}
            emissiveIntensity={2}
            toneMapped={false}
          />
        </mesh>
        <pointLight color={BLUE} intensity={3} distance={3} />
      </group>

      {/* Data streams */}
      {STREAMS.map((s, k) => (
        <Line
          key={k}
          ref={(el) => {
            beams.current[k] = el;
          }}
          points={beamPoints[k]}
          color={k === 3 ? PURPLE : BLUE}
          lineWidth={1.5}
          transparent
          opacity={0.12}
        />
      ))}
      <instancedMesh ref={stream} args={[undefined, undefined, STREAM_TOTAL]} frustumCulled={false}>
        <boxGeometry args={[0.09, 0.09, 0.09]} />
        <Neon color={BLUE} intensity={3} />
      </instancedMesh>
      {Array.from({ length: PULSE_TRAIL }, (_, k) => (
        <mesh
          key={k}
          ref={(el) => {
            pulses.current[k] = el;
          }}
          visible={false}
        >
          <sphereGeometry args={[0.1, 16, 16]} />
          <Neon color={k === 0 ? ICE : PURPLE} intensity={k === 0 ? 8 : 5 - k * 0.8} />
        </mesh>
      ))}

      {/* Local LLM: the neural core */}
      <Float speed={reducedMotion ? 0 : 2} floatIntensity={0.4} rotationIntensity={0.2}>
        <group position={[BRAIN_X, BRAIN_Y, 0]} scale={BRAIN_SCALE}>
          <mesh ref={brainCore}>
            <sphereGeometry args={[0.42, 64, 64]} />
            <meshStandardMaterial
              ref={brainMaterial}
              color="#f5e8ff"
              emissive={PURPLE}
              emissiveIntensity={4}
              toneMapped={false}
            />
          </mesh>
          <mesh ref={brainHalo}>
            <sphereGeometry args={[0.56, 48, 48]} />
            <meshBasicMaterial
              color={PURPLE}
              transparent
              opacity={0.18}
              blending={AdditiveBlending}
              depthWrite={false}
              toneMapped={false}
            />
          </mesh>
          <mesh ref={brainInner}>
            <icosahedronGeometry args={[0.72, 1]} />
            <Neon color={BLUE} intensity={3} wireframe transparent opacity={0.7} />
          </mesh>
          <group ref={brainOuter}>
            <mesh>
              <icosahedronGeometry args={[1, 2]} />
              <Neon color={PURPLE} intensity={1.5} wireframe transparent opacity={0.25} />
            </mesh>
            <points>
              <icosahedronGeometry args={[1, 2]} />
              <pointsMaterial color={ICE} size={0.05} sizeAttenuation toneMapped={false} />
            </points>
          </group>
          <group ref={brainOrbits}>
            {[0.5, -0.7].map((tilt) => (
              <mesh key={tilt} rotation={[Math.PI / 2 + tilt, 0, tilt]}>
                <torusGeometry args={[1.18, 0.008, 8, 128]} />
                <Neon color={BLUE} intensity={3} />
              </mesh>
            ))}
          </group>
          <pointLight ref={brainLight} color={PURPLE} intensity={4} distance={6} />
        </group>
      </Float>

      {/* Answer */}
      <group ref={answer} position={[BRAIN_X, BRAIN_Y, 0.3]} visible={false}>
        <mesh>
          <boxGeometry args={[ANSWER_WIDTH, ANSWER_HEIGHT, 0.04]} />
          <Glass color="#e9d5ff" emissive="#1a0b2e" emissiveIntensity={0.6} attenuationColor={PURPLE} />
        </mesh>
        <PanelFrame width={ANSWER_WIDTH} height={ANSWER_HEIGHT} color={ICE} intensity={5} />
        {ANSWER_LINES.map((w, i) => (
          <group
            key={w}
            ref={(el) => {
              answerLines.current[i] = el;
            }}
            position={[-0.5, 0.18 - i * 0.18, 0.03]}
          >
            <mesh position={[w / 2, 0, 0]}>
              <boxGeometry args={[w, 0.06, 0.01]} />
              <Neon color={ICE} intensity={4} />
            </mesh>
          </group>
        ))}
      </group>

      <Sparkles count={90} scale={[12, 6, 5]} size={1.8} speed={0.3} color={BLUE} opacity={0.5} />
      <Sparkles count={40} scale={[12, 6, 5]} size={1.4} speed={0.2} color={PURPLE} opacity={0.4} />
    </group>
  );
}

// No WebGL (old hardware, a disabled GPU) should cost the page one panel,
// not the whole landing page.
class CanvasBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

export default function ArchitectureVisualizer({ className = '' }) {
  const container = useRef(null);
  const stepRefs = useRef([]);
  const [onScreen, setOnScreen] = useState(true);

  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
  // OrbitControls claims touch gestures on the canvas, which would trap a
  // phone's scroll inside this panel. Drag-to-orbit is for mice only.
  const finePointer = useMediaQuery('(pointer: fine)');

  // Stop rendering while scrolled out of view.
  useEffect(() => {
    const el = container.current;
    if (!el || typeof IntersectionObserver === 'undefined') return undefined;

    const observer = new IntersectionObserver(([entry]) => setOnScreen(entry.isIntersecting), {
      rootMargin: '100px',
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={container}
      role="img"
      aria-label="How a local RAG pipeline works, entirely inside your machine: a PDF enters through the API gateway, the orchestrator splits it into chunks and stores their embeddings in ChromaDB, then retrieves the relevant chunks and sends them to a local Ollama model, which generates the answer."
      className={`relative h-96 w-full overflow-hidden rounded-2xl bg-black ${className}`}
    >
      <CanvasBoundary>
        <Canvas
          dpr={[1, 2]}
          frameloop={onScreen ? 'always' : 'never'}
          camera={{ position: [0, 1.2, 8.8], fov: 42 }}
          gl={{ antialias: true, powerPreference: 'high-performance' }}
        >
          <color attach="background" args={['#000000']} />
          <fog attach="fog" args={['#000000', 11, 22]} />
          <ambientLight intensity={0.2} />
          <pointLight position={[-4, 4, 4]} intensity={40} color={BLUE} />
          <pointLight position={[4, -1, 3]} intensity={30} color={PURPLE} />
          <pointLight position={[0, 5, -3]} intensity={20} color={ICE} />

          <Stars radius={40} depth={20} count={1500} factor={2} saturation={0} fade speed={0.5} />
          <Scene reducedMotion={reducedMotion} stepRefs={stepRefs} />

          {finePointer && (
            <OrbitControls
              enableZoom={false}
              enablePan={false}
              enableDamping
              rotateSpeed={0.4}
              minPolarAngle={1.25}
              maxPolarAngle={1.6}
              minAzimuthAngle={-0.6}
              maxAzimuthAngle={0.6}
            />
          )}
        </Canvas>
      </CanvasBoundary>

      <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-1.5 rounded-full border border-sky-400/30 bg-black/40 px-2.5 py-1 text-[11px] font-medium text-sky-200/80 backdrop-blur">
        <span className="size-1.5 rounded-full bg-sky-400 shadow-[0_0_6px_#38bdf8]" />
        Your machine · air-gapped
      </div>

      <ol className="pointer-events-none absolute inset-x-3 bottom-3 flex flex-wrap justify-center gap-1.5">
        {STAGES.map((stage, i) => (
          <li
            key={stage.label}
            ref={(el) => {
              stepRefs.current[i] = el;
            }}
            data-active={i === 0}
            className="rounded-full border border-white/10 bg-black/40 px-2.5 py-1 text-[11px] font-medium text-white/40 backdrop-blur transition-colors duration-300 data-[active=true]:border-sky-400/60 data-[active=true]:bg-sky-400/10 data-[active=true]:text-sky-200"
          >
            <span className="mr-1 tabular-nums opacity-60">{String(i + 1).padStart(2, '0')}</span>
            {stage.label}
          </li>
        ))}
      </ol>
    </div>
  );
}
