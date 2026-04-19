import {
  Group, Mesh, MeshBasicMaterial, CircleGeometry, RingGeometry,
  BufferGeometry, Vector3, Line, LineDashedMaterial, LineBasicMaterial,
  DoubleSide,
} from "three";
import {
  TIER_RADIUS, RING_COLORS, TIER_VISIBLE_ROLES, GROUND_Y,
} from "./constants3d";

export function buildGround(): Group {
  const group = new Group();

  const disc = new Mesh(
    new CircleGeometry(500, 64),
    new MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.28, depthWrite: false }),
  );
  disc.rotation.x = -Math.PI / 2;
  disc.position.y = GROUND_Y;
  group.add(disc);

  for (const role of TIER_VISIBLE_ROLES) {
    const r = TIER_RADIUS[role];
    const color = RING_COLORS[role];

    const pts: Vector3[] = [];
    for (let i = 0; i <= 128; i++) {
      const a = (i / 128) * Math.PI * 2;
      pts.push(new Vector3(Math.cos(a) * r, GROUND_Y + 1, Math.sin(a) * r));
    }
    const ringGeo = new BufferGeometry().setFromPoints(pts);
    const ringMat = new LineDashedMaterial({
      color, transparent: true, opacity: 0.38, dashSize: 4, gapSize: 6, depthWrite: false,
    });
    const ring = new Line(ringGeo, ringMat);
    ring.computeLineDistances();
    group.add(ring);

    const band = new Mesh(
      new RingGeometry(r - 6, r, 96),
      new MeshBasicMaterial({ color, transparent: true, opacity: 0.07, side: DoubleSide, depthWrite: false }),
    );
    band.rotation.x = -Math.PI / 2;
    band.position.y = GROUND_Y + 0.5;
    group.add(band);
  }

  for (let k = 0; k < 12; k++) {
    const a = (k / 12) * Math.PI * 2;
    const pts = [
      new Vector3(0, GROUND_Y + 1, 0),
      new Vector3(Math.cos(a) * 340, GROUND_Y + 1, Math.sin(a) * 340),
    ];
    const spokeGeo = new BufferGeometry().setFromPoints(pts);
    const spokeMat = new LineBasicMaterial({
      color: 0x9fb3c2, transparent: true, opacity: 0.18, depthWrite: false,
    });
    group.add(new Line(spokeGeo, spokeMat));
  }

  const colGeo = new BufferGeometry().setFromPoints([
    new Vector3(0, GROUND_Y, 0),
    new Vector3(0, 90, 0),
  ]);
  const colMat = new LineDashedMaterial({
    color: 0x0f2a2d, transparent: true, opacity: 0.2, dashSize: 3, gapSize: 4, depthWrite: false,
  });
  const column = new Line(colGeo, colMat);
  column.computeLineDistances();
  group.add(column);

  return group;
}
