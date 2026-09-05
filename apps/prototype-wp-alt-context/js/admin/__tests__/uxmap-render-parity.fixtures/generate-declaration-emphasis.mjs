// Regenerate the shared matrix consumed by Vitest and both Python check paths.
import fs from 'node:fs';

const file = new URL('./declaration-mutations.json', import.meta.url);
const fixture = JSON.parse(fs.readFileSync(file, 'utf8'));
fixture.emphasis = {};
for (const key of fixture.keys) {
  const cases = [];
  for (const marker of ['*', '_']) {
    for (const count of [1, 2]) {
      for (const placement of ['whole', 'first', 'last', 'both']) {
        for (const inside of [false, true]) {
          const wrap = marker.repeat(count);
          const words = key.split(' ');
          let label;
          if (placement === 'whole') {
            label = wrap + key + (inside ? ':' : '') + wrap + (inside ? '' : ':');
          } else {
            label = words.map((word, index) => {
              const last = index === words.length - 1;
              const selected = placement === 'both' ||
                (placement === 'first' && index === 0) || (placement === 'last' && last);
              const colon = inside && last ? ':' : '';
              return selected ? wrap + word + colon + wrap : word + colon;
            }).join(' ') + (inside ? '' : ':');
          }
          cases.push(label + ' {value}');
        }
      }
    }
  }
  fixture.emphasis[key] = cases;
}
fs.writeFileSync(file, JSON.stringify(fixture, null, 2) + '\n');
