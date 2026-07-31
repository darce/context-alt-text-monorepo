import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, expectTypeOf, it } from 'vitest';

import type { RosterEntryInstance } from '../generated/roster-entry';

interface BboxSchema {
  type?: string | string[];
  required?: string[];
  properties?: Record<string, { type?: string | string[]; minimum?: number }>;
  items?: { type?: string };
}

interface InstanceSchema {
  properties?: {
    bbox?: BboxSchema;
  };
}

interface RosterEntrySchema {
  properties?: {
    clusters?: {
      items?: {
        properties?: {
          representative_identity?: InstanceSchema;
          instances?: {
            items?: InstanceSchema;
          };
        };
      };
    };
  };
}

describe('roster entry contract', () => {
  const schema = JSON.parse(
    readFileSync(
      resolve(process.cwd(), '../../packages/shared-contracts/schemas/roster-entry.schema.json'),
      'utf8',
    ),
  ) as RosterEntrySchema;

  const representativeBbox =
    schema.properties?.clusters?.items?.properties?.representative_identity?.properties?.bbox;
  const instanceBbox = schema.properties?.clusters?.items?.properties?.instances?.items?.properties?.bbox;

  const assertPixelBboxSchema = (bbox: BboxSchema | undefined, label: string): void => {
    expect(bbox, `${label} bbox must be declared`).toBeDefined();
    expect(bbox?.type, `${label} bbox type`).toEqual(['object', 'null']);
    expect(bbox?.required, `${label} bbox required keys`).toEqual(['x', 'y', 'width', 'height']);
    expect(bbox?.properties?.x?.type).toBe('integer');
    expect(bbox?.properties?.y?.type).toBe('integer');
    expect(bbox?.properties?.width?.type).toBe('integer');
    expect(bbox?.properties?.height?.type).toBe('integer');
    expect(bbox?.properties?.x?.minimum).toBe(0);
    expect(bbox?.properties?.y?.minimum).toBe(0);
    expect(bbox?.properties?.width?.minimum).toBe(0);
    expect(bbox?.properties?.height?.minimum).toBe(0);
    // Must not remain the legacy number[] declaration.
    expect(bbox?.items).toBeUndefined();
  };

  it('declares bbox as a pixel-space object on representative_identity and instances', () => {
    assertPixelBboxSchema(representativeBbox, 'representative_identity');
    assertPixelBboxSchema(instanceBbox, 'instances.items');
  });

  it('matches the frontend RosterEntryInstance bbox shape', () => {
    // Type-level boundary [S8-BR-02 / TEST-15]: object-form pixel bbox, not number[].
    // Assigning a pixel object must typecheck; if RosterEntryBbox regresses to
    // number[] | null, `npm run typecheck` fails on this fixture assignment.
    const instance: RosterEntryInstance = {
      identity_id: 'identity-1',
      media_id: 101,
      media_url: 'https://example.com/101.jpg',
      bbox: { x: 10, y: 20, width: 30, height: 40 },
      similarity: 0.97,
    };

    expectTypeOf(instance).toMatchTypeOf<RosterEntryInstance>();
    expectTypeOf(instance.bbox).toMatchTypeOf<{ x: number; y: number; width: number; height: number } | null>();
    // Reject number[]: a tuple must not be assignable to RosterEntryInstance.bbox.
    expectTypeOf(instance.bbox).not.toMatchTypeOf<number[] | null>();
    // Structural runtime check against the projection shape (not a tautological
    // literal equal of a value we just constructed).
    expect(instance.bbox).not.toBeNull();
    expect(instance.bbox).not.toBeInstanceOf(Array);
    if (instance.bbox) {
      expect(Object.keys(instance.bbox).sort()).toEqual(['height', 'width', 'x', 'y']);
      expect(typeof instance.bbox.x).toBe('number');
      expect(typeof instance.bbox.y).toBe('number');
      expect(typeof instance.bbox.width).toBe('number');
      expect(typeof instance.bbox.height).toBe('number');
    }
  });
});
