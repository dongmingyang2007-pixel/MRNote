import MemoryMock from "./mocks/MemoryMock";
import FollowupMock from "./mocks/FollowupMock";
import DigestMock from "./mocks/DigestMock";

/**
 * The right half of the Hero. Three mocks overlap and float idly on
 * a soft blue stage — the first picture a visitor sees of "what this
 * product looks like". No drag here (that's LiveCanvasDemo's job) —
 * this stays calm and decorative.
 *
 * Server component. Motion is CSS-only.
 */
export default function HeroCanvasStage() {
  return (
    <div className="marketing-canvas-stage">
      <div className="marketing-canvas-stage__slot marketing-canvas-stage__slot--a">
        <MemoryMock />
      </div>
      <div className="marketing-canvas-stage__slot marketing-canvas-stage__slot--b">
        <FollowupMock />
      </div>
      <div className="marketing-canvas-stage__slot marketing-canvas-stage__slot--c">
        <DigestMock />
      </div>
    </div>
  );
}
