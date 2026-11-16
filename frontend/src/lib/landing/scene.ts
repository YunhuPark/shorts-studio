import type { Mesh, Texture } from "three";

// The landing page's background: a rainy-night corridor of 9:16 frames (stills from the demo video) that the camera
// flies through as the page scrolls. three.js is imported lazily so the first paint does not wait for it.

export type SceneHandle = {
  /** 0..1, how far the visitor is through the journey; the camera eases toward it */
  setProgress(p: number): void;
  /** pointer position as -1..1, for a small parallax */
  setPointer(x: number, y: number): void;
  dispose(): void;
};

export type SceneOptions = { reduced: boolean; narrow: boolean };

const BG = 0x070b10;
const AMBER = 0xffb347;
const RAIN = 0x9fd8ff;
const SPACING = 2.6;

export async function createScene(host: HTMLElement, sources: string[], opts: SceneOptions): Promise<SceneHandle> {
  const T = await import("three");

  // the canvas is created here and removed on dispose: a canvas whose context was force-lost cannot be reused by a remount
  const canvas = document.createElement("canvas");
  canvas.setAttribute("aria-hidden", "true");
  canvas.style.cssText = "position:absolute;inset:0;width:100%;height:100%;display:block";
  host.appendChild(canvas);
  let renderer: InstanceType<typeof T.WebGLRenderer>;
  try {
    renderer = new T.WebGLRenderer({ canvas, antialias: !opts.narrow, powerPreference: "high-performance" });
  } catch (error) {
    canvas.remove();
    throw error;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, opts.narrow ? 1.5 : 2));
  renderer.setClearColor(BG, 1);

  const scene = new T.Scene();
  scene.fog = new T.FogExp2(BG, opts.narrow ? 0.05 : 0.055);
  const camera = new T.PerspectiveCamera(opts.narrow ? 58 : 50, 1, 0.1, 80);

  const count = sources.length;
  const scale = opts.narrow ? 0.85 : 1;
  const frameGeometry = new T.PlaneGeometry(1.35 * scale, 2.4 * scale);
  const edgeGeometry = new T.EdgesGeometry(frameGeometry);
  const edgeMaterial = new T.LineBasicMaterial({ color: AMBER, transparent: true, opacity: 0.32 });
  const loader = new T.TextureLoader();
  const textures: Texture[] = [];
  const materials: InstanceType<typeof T.MeshBasicMaterial>[] = [];
  const frames: { mesh: Mesh; baseY: number; phase: number; born: number }[] = [];

  sources.forEach((src, i) => {
    const angle = i * 1.35;
    const radius = (opts.narrow ? 1.55 : 2.3) + (i % 3) * 0.35;
    const x = Math.cos(angle) * radius + (opts.narrow ? 0 : 0.7);
    const y = Math.sin(angle * 0.8) * 0.9 + (opts.narrow ? 1.05 : 0); // on a phone the text owns the lower half, so the frames ride higher
    const material = new T.MeshBasicMaterial({ color: 0xffffff, toneMapped: false, transparent: true, opacity: 0 });
    materials.push(material);
    const mesh = new T.Mesh(frameGeometry, material);
    mesh.position.set(x, y, -i * SPACING);
    mesh.rotation.set(0, -x * 0.12, Math.sin(i * 2.1) * 0.06);
    mesh.add(new T.LineSegments(edgeGeometry, edgeMaterial));
    scene.add(mesh);
    frames.push({ mesh, baseY: y, phase: i * 1.7, born: -1 });
    loader.load(src, (texture) => {
      texture.colorSpace = T.SRGBColorSpace;
      textures.push(texture);
      material.map = texture;
      material.needsUpdate = true;
      frames[i].born = performance.now();
    });
  });

  // streaks of rain: they fall a little and wrap around, which is what makes the corridor feel alive when the page is still
  const streaks = opts.narrow ? 160 : 280;
  const rainPositions = new Float32Array(streaks * 6);
  const span = (count - 1) * SPACING + 18;
  for (let s = 0; s < streaks; s++) {
    const x = (Math.random() - 0.5) * 18;
    const y = -6 + Math.random() * 14;
    const z = 8 - Math.random() * span;
    rainPositions.set([x, y, z, x, y - 0.55, z], s * 6);
  }
  const rainGeometry = new T.BufferGeometry();
  rainGeometry.setAttribute("position", new T.BufferAttribute(rainPositions, 3));
  const rainMaterial = new T.LineBasicMaterial({ color: RAIN, transparent: true, opacity: 0.2 });
  scene.add(new T.LineSegments(rainGeometry, rainMaterial));

  const endZ = -(count - 1) * SPACING + 3;
  const startZ = 6;
  let target = 0;
  let current = 0;
  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  let last = performance.now();
  let raf = 0;
  let disposed = false;

  const resize = () => {
    const w = host.clientWidth || window.innerWidth;
    const h = host.clientHeight || window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  const observer = new ResizeObserver(resize);
  observer.observe(host);
  resize();

  const frame = (now: number) => {
    if (disposed) return;
    raf = requestAnimationFrame(frame);
    const dt = Math.min((now - last) / 1000, 0.1);
    last = now;
    current += (target - current) * (1 - Math.exp(-dt * 5));
    pointer.x += (pointer.tx - pointer.x) * (1 - Math.exp(-dt * 4));
    pointer.y += (pointer.ty - pointer.y) * (1 - Math.exp(-dt * 4));

    const p = current;
    camera.position.set(
      Math.sin(p * Math.PI * 3) * (opts.narrow ? 0.25 : 0.45) + pointer.x * 0.35,
      Math.cos(p * Math.PI * 2) * 0.25 + pointer.y * 0.2,
      startZ + (endZ - startZ) * p,
    );
    camera.rotation.z = Math.sin(p * Math.PI * 2) * 0.03;
    camera.lookAt(camera.position.x * 0.5, camera.position.y * 0.5, camera.position.z - 6);

    const t = now / 1000;
    for (const f of frames) {
      if (!opts.reduced) f.mesh.position.y = f.baseY + Math.sin(t * 0.5 + f.phase) * 0.08;
      const mat = f.mesh.material as InstanceType<typeof T.MeshBasicMaterial>;
      mat.opacity = f.born < 0 ? 0 : Math.min(1, (now - f.born) / 700);
    }
    if (!opts.reduced) {
      const a = rainGeometry.getAttribute("position") as InstanceType<typeof T.BufferAttribute>;
      const fall = 6.5 * dt;
      for (let s = 0; s < streaks; s++) {
        const i = s * 6;
        rainPositions[i + 1] -= fall;
        rainPositions[i + 4] -= fall;
        if (rainPositions[i + 4] < -6) {
          rainPositions[i + 1] += 14;
          rainPositions[i + 4] += 14;
        }
      }
      a.needsUpdate = true;
    }
    renderer.render(scene, camera);
  };
  raf = requestAnimationFrame(frame);

  return {
    setProgress(p) {
      target = Math.min(1, Math.max(0, p));
    },
    setPointer(x, y) {
      pointer.tx = x;
      pointer.ty = y;
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(raf);
      observer.disconnect();
      frameGeometry.dispose();
      edgeGeometry.dispose();
      edgeMaterial.dispose();
      rainGeometry.dispose();
      rainMaterial.dispose();
      materials.forEach((m) => m.dispose());
      textures.forEach((tex) => tex.dispose());
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.remove();
    },
  };
}
