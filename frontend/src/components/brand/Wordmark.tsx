import Link from "next/link";

/**
 * The wordmark: "arbitrium" in Unbounded 400, then a lime "/".
 *
 * Text, not an image — it inherits the bundled font, stays crisp at any size
 * and costs no asset. Lowercase in the SOURCE rather than via text-transform,
 * so it reads the same with styles off and to a screen reader. No letter
 * spacing on either character, and both are the same size: the slash is part
 * of the word, not a decoration beside it.
 *
 * The slash is aria-hidden. "arbitrium slash" is not the product's name.
 *
 * The share-preview image draws the same mark in its own sandbox (see
 * app/events/[id]/opengraph-image.tsx), with the same font file and colours.
 */
export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span
      className={`display inline-flex items-baseline leading-none tracking-normal text-text ${className}`}
    >
      arbitrium
      <span aria-hidden className="text-signal">
        /
      </span>
    </span>
  );
}

/** The header's home link: the wordmark, named "Arbitrium home" for assistive tech. */
export function WordmarkLink({ className = "" }: { className?: string }) {
  return (
    <Link href="/" aria-label="Arbitrium home" className={`tap shrink-0 ${className}`}>
      <Wordmark className="text-[16px] sm:text-[19px]" />
    </Link>
  );
}
