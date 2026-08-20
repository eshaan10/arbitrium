/**
 * Colour maths for the palette monitor.
 *
 * Deliberately dependency-free and written out longhand: this is the code the
 * palette test uses to check the design system, so it must not share an
 * implementation with anything the design system itself uses. A shared helper
 * would let one bug agree with itself and pass.
 */

export interface Rgb {
  r: number;
  g: number;
  b: number;
}

export function hexToRgb(hex: string): Rgb {
  const h = hex.replace("#", "").trim();
  const full =
    h.length === 3
      ? h
          .split("")
          .map((c) => c + c)
          .join("")
      : h;
  return {
    r: parseInt(full.slice(0, 2), 16) / 255,
    g: parseInt(full.slice(2, 4), 16) / 255,
    b: parseInt(full.slice(4, 6), 16) / 255,
  };
}

/** sRGB gamma → linear light. */
function linearise(c: number): number {
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/** WCAG 2.x relative luminance. */
export function luminance(hex: string): number {
  const { r, g, b } = hexToRgb(hex);
  return 0.2126 * linearise(r) + 0.7152 * linearise(g) + 0.0722 * linearise(b);
}

/** WCAG contrast ratio, 1–21. */
export function contrast(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/* --- OKLab / OKLCH ------------------------------------------------------- */

export interface Oklch {
  l: number;
  c: number;
  h: number;
}

export function oklch(hex: string): Oklch {
  const { r, g, b } = hexToRgb(hex);
  const lr = linearise(r);
  const lg = linearise(g);
  const lb = linearise(b);

  const l_ = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
  const m_ = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
  const s_ = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);

  const L = 0.2104542553 * l_ + 0.793617785 * m_ - 0.0040720468 * s_;
  const A = 1.9779984951 * l_ - 2.428592205 * m_ + 0.4505937099 * s_;
  const B = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.808675766 * s_;

  const hue = (Math.atan2(B, A) * 180) / Math.PI;
  return { l: L, c: Math.sqrt(A * A + B * B), h: hue < 0 ? hue + 360 : hue };
}

/** Perceptual distance in OKLab. Used for "can these two be told apart?". */
export function deltaE(a: string, b: string): number {
  const x = oklch(a);
  const y = oklch(b);
  const ax = x.c * Math.cos((x.h * Math.PI) / 180);
  const ay = x.c * Math.sin((x.h * Math.PI) / 180);
  const bx = y.c * Math.cos((y.h * Math.PI) / 180);
  const by = y.c * Math.sin((y.h * Math.PI) / 180);
  // Scaled to a 0–100 range so the numbers read like a familiar ΔE.
  return 100 * Math.sqrt((x.l - y.l) ** 2 + (ax - bx) ** 2 + (ay - by) ** 2);
}

/* --- colour-vision deficiency -------------------------------------------- */

type Cvd = "protan" | "deutan";

/**
 * Brettel/Viénot-style simulation in linear sRGB. Approximate by design — it
 * is used to reject pairs that collapse, not to render for anyone.
 */
const CVD_MATRIX: Record<Cvd, number[][]> = {
  protan: [
    [0.1121, 0.8853, -0.0005],
    [0.1127, 0.8897, -0.0001],
    [0.0045, 0.0, 1.0019],
  ],
  deutan: [
    [0.292, 0.7054, -0.0003],
    [0.2934, 0.7089, 0.0006],
    [-0.0209, 0.0257, 0.9979],
  ],
};

function toHex(n: number): string {
  const v = Math.max(0, Math.min(255, Math.round(n * 255)));
  return v.toString(16).padStart(2, "0");
}

export function simulate(hex: string, kind: Cvd): string {
  const m = CVD_MATRIX[kind];
  const { r, g, b } = hexToRgb(hex);
  const [lr, lg, lb] = [linearise(r), linearise(g), linearise(b)];
  const out = m.map((row) => row[0] * lr + row[1] * lg + row[2] * lb);
  const gamma = (c: number) =>
    c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(Math.max(c, 0), 1 / 2.4) - 0.055;
  return `#${out.map((c) => toHex(gamma(c))).join("")}`;
}
