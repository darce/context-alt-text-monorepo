/**
 * Parse the semantic, machine-rendered parts of a UX-map Markdown artifact.
 *
 * This deliberately ignores the lossy ASCII screen sketches. The canonical renderer
 * emits lossless tables/lists for every value represented here, so callers can compare
 * this projection with the JSON SSOT instead of checking a handful of substrings.
 */

export interface RenderParityMap {
  map_ref: string;
  product: string;
  source_fixture: string | null;
  goals: string[];
  jobs: Array<{ id: string; label: string }>;
  screens: Array<{
    id: string;
    kind: string;
    title: string;
    purpose: string;
    route: string;
    url_params: string[];
    states: string[];
    action_states?: string[];
    zones: Array<{ id: string; label: string; role: string; states: string[] }>;
  }>;
  actions: Array<{
    id: string;
    verb: string;
    target: string;
    hierarchy: string;
    costly: boolean;
    irreversible: boolean;
    preview_required: boolean;
    screen_id: string | null;
    when?: string[];
  }>;
  flows: Array<{
    id: string;
    label: string;
    job: string;
    steps: Array<{ screen_id: string; branch_label: string | null }>;
  }>;
  domain_state_mappings?: Array<{ domain_states: string[]; canonical_state: string }>;
  slices?: string[];
  open_questions: string[];
  not_doing: string[];
}

export interface RenderParityIndex {
  zoneIds: string[];
  actionIds: string[];
  zoneLabels: string[];
  states: string[];
}

export interface RenderedUxMapProjection extends RenderParityMap {
  parityIndex: RenderParityIndex;
}

export interface UxMapRenderSource extends Omit<RenderParityMap, 'screens' | 'flows'> {
  screens: Array<
    Omit<RenderParityMap['screens'][number], 'url_params' | 'zones'> & {
      states?: string[];
      url_params?: string[];
      zones?: RenderParityMap['screens'][number]['zones'];
    }
  >;
  flows: Array<{
    id: string;
    label: string | null;
    job: string;
    steps: Array<{ screen_id: string; branch_label: string | null }>;
  }>;
}

const section = (markdown: string, heading: string): string => {
  const marker = `## ${heading}`;
  const start = markdown.indexOf(marker);
  if (start < 0) {
    return '';
  }
  const next = markdown.indexOf('\n## ', start + marker.length);
  return markdown.slice(start + marker.length, next < 0 ? markdown.length : next).trim();
};

const unquote = (value: string): string => value.replace(/^`|`$/g, '');

const splitTableRow = (line: string): string[] => {
  const cells: string[] = [];
  let cell = '';
  for (const char of line.slice(1, -1)) {
    if (char === '|' && !cell.endsWith('\\')) {
      cells.push(cell.trim().replaceAll('\\|', '|'));
      cell = '';
    } else {
      cell += char;
    }
  }
  cells.push(cell.trim().replaceAll('\\|', '|'));
  return cells;
};

const listSection = (markdown: string, heading: string): string[] =>
  section(markdown, heading)
    .split('\n')
    .filter((line) => line.startsWith('- '))
    .map((line) => line.slice(2));

const parseScreenStates = (block: string, screenId: string): string[] => {
  const explicit = /^Screen states:\s*(.+?)\.?$/m.exec(block)?.[1];
  const explicitStates = explicit
    ? explicit
        .split(/,\s*|\s+/)
        .map(unquote)
        .filter(Boolean)
    : undefined;
  const asciiLines = block.split('\n').filter((line) => /^\| states(?:\+|):/.test(line));
  const asciiStates = asciiLines.flatMap((line) => {
    const body = /^\| states(?:\+|):\s*(.*?)\s*\|$/.exec(line)?.[1] ?? '';
    return body
      .split('|')
      .map((state) => state.trim())
      .filter(Boolean);
  });
  if (asciiStates.includes('…')) {
    throw new Error(`screen ${screenId} has truncated ASCII states`);
  }
  if (explicitStates && asciiStates.length > 0 && JSON.stringify(explicitStates) !== JSON.stringify(asciiStates)) {
    throw new Error(`screen ${screenId} has different states in its lossless block and ASCII sketch`);
  }
  return explicitStates ?? asciiStates;
};

const parseScreens = (markdown: string): RenderParityMap['screens'] => {
  const screensSection = section(markdown, 'Screens');
  const summary = screensSection.split('\n### ')[0] ?? '';
  const fifthColumn = /^\| id \| kind \| route \| title \| ([^|]+) \|$/m.exec(summary)?.[1]?.trim();
  const summaries = new Map<
    string,
    Pick<RenderParityMap['screens'][number], 'id' | 'kind' | 'title' | 'route' | 'url_params'>
  >();

  for (const line of summary.split('\n')) {
    if (!line.startsWith('| `')) {
      continue;
    }
    const [rawId, kind, rawRoute, title, rawParams = '—'] = splitTableRow(line);
    const id = unquote(rawId ?? '');
    if (summaries.has(id)) {
      throw new Error(`screen ${id} has duplicate Screens table rows`);
    }
    summaries.set(id, {
      id,
      kind: kind ?? '',
      route: unquote(rawRoute ?? ''),
      title: title ?? '',
      url_params:
        fifthColumn !== 'url_params' || rawParams === '—' ? [] : rawParams.split(', ').filter(Boolean).map(unquote),
    });
  }

  const blocks = [...screensSection.matchAll(/^### .+ \(`([^`]+)`\)\n([\s\S]*?)(?=^### |(?![\s\S]))/gm)];
  const detailIds = new Set<string>();
  const screens = blocks.map((match) => {
    const id = match[1] ?? '';
    if (detailIds.has(id)) {
      throw new Error(`screen ${id} has duplicate detail blocks`);
    }
    detailIds.add(id);
    const block = match[2] ?? '';
    const base = summaries.get(id);
    if (!base) {
      throw new Error(`screen ${id} has a detail block but no Screens table row`);
    }
    const purpose = /^Purpose: (.*)$/m.exec(block)?.[1] ?? '';
    const params = /^url_params: (.*)$/m.exec(block)?.[1];
    const parsedParams = params ? params.split(', ').map(unquote) : base.url_params;
    if (params && fifthColumn === 'url_params' && JSON.stringify(parsedParams) !== JSON.stringify(base.url_params)) {
      throw new Error(`screen ${id} has different url_params in the Screens table and detail block`);
    }
    const zones: RenderParityMap['screens'][number]['zones'] = [];
    for (const line of block.split('\n')) {
      if (!line.startsWith('| `')) {
        continue;
      }
      const [rawZoneId, label, role, rawStates] = splitTableRow(line);
      zones.push({
        id: unquote(rawZoneId ?? ''),
        label: label ?? '',
        role: role ?? '',
        states: (rawStates ?? '').split(', ').filter(Boolean),
      });
    }
    return {
      ...base,
      purpose,
      url_params: parsedParams,
      states: parseScreenStates(block, id),
      ...(/^Action states: (.+)$/m.test(block)
        ? { action_states: /^Action states: (.+)$/m.exec(block)![1]!.split(', ') }
        : {}),
      zones,
    };
  });

  for (const id of summaries.keys()) {
    if (!detailIds.has(id)) {
      throw new Error(`screen ${id} has a Screens table row but no detail block`);
    }
  }
  return screens.sort((a, b) => a.id.localeCompare(b.id));
};

const parseBooleanCell = (value: string | undefined, actionId: string, column: string): boolean => {
  if (value === 'yes') {
    return true;
  }
  if (value === 'no') {
    return false;
  }
  throw new Error(`action ${actionId} ${column} must be exactly yes or no; received ${JSON.stringify(value ?? '')}`);
};

const parseActions = (markdown: string): RenderParityMap['actions'] => {
  const actions: RenderParityMap['actions'] = [];
  for (const line of section(markdown, 'Actions').split('\n')) {
    if (!line.startsWith('| `')) {
      continue;
    }
    const [rawId, verb, target, hierarchy, costly, irreversible, previewRequired, rawScreenId, when] =
      splitTableRow(line);
    const id = unquote(rawId ?? '');
    actions.push({
      id,
      verb: verb ?? '',
      target: unquote(target ?? ''),
      hierarchy: hierarchy ?? '',
      costly: parseBooleanCell(costly, id, 'costly'),
      irreversible: parseBooleanCell(irreversible, id, 'irreversible'),
      preview_required: parseBooleanCell(previewRequired, id, 'preview_required'),
      screen_id: rawScreenId === '—' ? null : unquote(rawScreenId ?? ''),
      ...(when !== undefined && when !== 'always' ? { when: when.split(', ') } : {}),
    });
  }
  return actions;
};

const parseFlows = (markdown: string): RenderParityMap['flows'] => {
  const flowsSection = section(markdown, 'Flows');
  const blocks = [...flowsSection.matchAll(/^### (.+) \(`([^`]+)`\)\n([\s\S]*?)(?=^### |(?![\s\S]))/gm)];
  return blocks.map((match) => {
    const body = match[3] ?? '';
    const id = match[2] ?? '';
    const job = /%% flow: .* job=([^\s]+)$/m.exec(body)?.[1] ?? '';
    const encodedSteps = /^\s*%% steps: (.+)$/m.exec(body)?.[1];
    if (!encodedSteps) {
      throw new Error(`flow ${id} has no lossless ordered steps comment`);
    }
    const steps = JSON.parse(encodedSteps) as unknown;
    if (
      !Array.isArray(steps) ||
      steps.length === 0 ||
      steps.some(
        (step) =>
          typeof step !== 'object' ||
          step === null ||
          typeof (step as Record<string, unknown>).screen_id !== 'string' ||
          !('branch_label' in step) ||
          ![null, 'string'].includes(
            (step as Record<string, unknown>).branch_label === null
              ? null
              : typeof (step as Record<string, unknown>).branch_label,
          ),
      )
    ) {
      throw new Error(`flow ${id} has invalid lossless ordered steps`);
    }
    return {
      id,
      label: match[1] ?? '',
      job,
      steps: steps as Array<{ screen_id: string; branch_label: string | null }>,
    };
  });
};

const parseDomainStateMappings = (markdown: string): RenderParityMap['domain_state_mappings'] => {
  const mappings: NonNullable<RenderParityMap['domain_state_mappings']> = [];
  for (const line of section(markdown, 'Domain state mapping').split('\n')) {
    if (!line.startsWith('| `')) {
      continue;
    }
    const [rawDomainStates, rawCanonical] = splitTableRow(line);
    mappings.push({
      domain_states: (rawDomainStates ?? '').split(', ').map(unquote),
      canonical_state: unquote(rawCanonical ?? ''),
    });
  }
  return mappings.length > 0 ? mappings : undefined;
};

const parseParityIndex = (markdown: string): RenderParityIndex => {
  const parity = section(markdown, 'Parity index');
  const valueAfter = (prefix: string): string[] => {
    const raw = parity
      .split('\n')
      .find((line) => line.startsWith(prefix))
      ?.slice(prefix.length)
      .trim();
    return raw ? raw.split(' ') : [];
  };
  const labelsBlock =
    /Zone labels(?: \(verbatim[^\n]*\))?:\n\n([\s\S]*?)\n\n(?:States \(all zones and screens\)|Screen states):/.exec(
      parity,
    )?.[1];
  return {
    zoneIds: valueAfter('Zone ids:'),
    actionIds: valueAfter('Action ids:'),
    zoneLabels: (labelsBlock ?? '')
      .split('\n')
      .filter((line) => line.startsWith('- '))
      .map((line) => line.slice(2)),
    states: valueAfter('States (all zones and screens):').length
      ? valueAfter('States (all zones and screens):')
      : valueAfter('Screen states:'),
  };
};

export const projectUxMapForRenderParity = (doc: UxMapRenderSource): RenderedUxMapProjection => {
  const states: string[] = [];
  const zones = doc.screens.flatMap((screen) => screen.zones ?? []);
  for (const screen of doc.screens) {
    for (const state of screen.states ?? []) {
      if (!states.includes(state)) {
        states.push(state);
      }
    }
    for (const zone of screen.zones ?? []) {
      for (const state of zone.states) {
        if (!states.includes(state)) {
          states.push(state);
        }
      }
    }
  }
  return {
    map_ref: doc.map_ref,
    product: doc.product,
    source_fixture: doc.source_fixture,
    goals: doc.goals,
    jobs: doc.jobs,
    screens: doc.screens
      .map((screen) => ({
        id: screen.id,
        kind: screen.kind,
        title: screen.title,
        purpose: screen.purpose,
        route: screen.route,
        url_params: screen.url_params ?? [],
        states: screen.states ?? [],
        ...(screen.action_states ? { action_states: screen.action_states } : {}),
        zones: (screen.zones ?? []).map((zone) => ({
          id: zone.id,
          label: zone.label,
          role: zone.role,
          states: zone.states ?? [],
        })),
      }))
      .sort((a, b) => a.id.localeCompare(b.id)),
    actions: doc.actions,
    flows: doc.flows.map((flow) => ({
      id: flow.id,
      label: flow.label ?? flow.id,
      job: flow.job,
      steps: flow.steps.map((step) => ({
        screen_id: step.screen_id,
        branch_label: step.branch_label ?? null,
      })),
    })),
    ...(doc.domain_state_mappings ? { domain_state_mappings: doc.domain_state_mappings } : {}),
    ...(doc.slices ? { slices: doc.slices } : {}),
    open_questions: doc.open_questions,
    not_doing: doc.not_doing,
    parityIndex: {
      zoneIds: zones.map((zone) => zone.id),
      actionIds: doc.actions.map((action) => action.id),
      zoneLabels: zones.map((zone) => zone.label),
      states,
    },
  };
};

export const parseRenderedUxMap = (markdown: string): RenderedUxMapProjection => {
  const mapRef = /^# UX Map — (.+)$/m.exec(markdown)?.[1] ?? '';
  const product = /^\*\*Product:\*\* `([^`]*)`$/m.exec(markdown)?.[1] ?? '';
  const sourceFixture = /^\*\*Source fixture:\*\* `([^`]*)`$/m.exec(markdown)?.[1] ?? null;
  const jobs = listSection(markdown, 'Jobs').map((line) => {
    const match = /^`([^`]+)` — (.*)$/.exec(line);
    return { id: match?.[1] ?? '', label: match?.[2] ?? '' };
  });

  return {
    map_ref: mapRef,
    product,
    source_fixture: sourceFixture,
    goals: listSection(markdown, 'Goals'),
    jobs,
    screens: parseScreens(markdown),
    actions: parseActions(markdown),
    ...(section(markdown, 'Suggested task-slice decomposition (from map)')
      ? {
          slices: section(markdown, 'Suggested task-slice decomposition (from map)')
            .split('\n')
            .filter((line) => /^\d+\. /.test(line))
            .map((line) => line.replace(/^\d+\. /, '')),
        }
      : {}),
    flows: parseFlows(markdown),
    ...(parseDomainStateMappings(markdown) ? { domain_state_mappings: parseDomainStateMappings(markdown) } : {}),
    open_questions: listSection(markdown, 'Open questions'),
    not_doing: listSection(markdown, 'Not doing'),
    parityIndex: parseParityIndex(markdown),
  };
};
