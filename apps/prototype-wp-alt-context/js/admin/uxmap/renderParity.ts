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

export interface UxMapRenderSource extends Omit<RenderParityMap, 'screens' | 'flows' | 'actions'> {
  actions: Array<
    Omit<RenderParityMap['actions'][number], 'costly' | 'irreversible' | 'preview_required' | 'screen_id'> & {
      costly?: boolean;
      irreversible?: boolean;
      preview_required?: boolean;
      screen_id?: string | null;
    }
  >;
  screens: Array<
    Omit<RenderParityMap['screens'][number], 'states' | 'url_params' | 'zones'> & {
      states?: string[];
      url_params?: string[];
      zones?: Array<Omit<RenderParityMap['screens'][number]['zones'][number], 'states'> & { states?: string[] }>;
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
  const headings = [...markdown.matchAll(/^ {0,3}##[ \t]+([^\r\n]*?)(?:[ \t]+#+)?[ \t]*\r?$/gm)];
  const matches = headings.filter((match) => match[1] === heading);
  if (matches.length > 1) {
    throw new Error(`duplicate machine-owned section: ${heading}`);
  }
  const match = matches[0];
  if (!match) {
    return '';
  }
  const next = headings[headings.indexOf(match) + 1];
  // Preserve indentation so malformed table rows cannot become canonical here.
  return markdown
    .slice(match.index! + match[0].length, next?.index ?? markdown.length)
    .replace(/^[\r\n]+|[\r\n]+$/g, '');
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

export const SCREEN_METADATA_KEYS = ['Purpose', 'url_params', 'Action states', 'Screen states'] as const;
type MetadataKey = (typeof SCREEN_METADATA_KEYS)[number];

// Both Python --check branches call this parser. Scan every line once, including
// code indentation and Markdown containers: formatting must not hide a declaration.
const scanDeclarations = (block: string, screenId: string, firstLine: number): Map<MetadataKey, string> => {
  const declarations = new Map<MetadataKey, string>();
  const locations = new Map<MetadataKey, number>();
  for (const [index, line] of block.split('\n').entries()) {
    const candidate = line.trimStart().replace(/^(?:(?:>|[-+*]|\d+[.)])\s*)+/, '').trim();
    const colon = candidate.indexOf(':');
    if (colon < 0) continue;
    const label = candidate.slice(0, colon).replace(/__|[*`]/g, '').trim().replace(/\s+/g, ' ').toLowerCase();
    const key = SCREEN_METADATA_KEYS.find((field) => field.toLowerCase() === label);
    if (!key) continue;
    const lineNumber = firstLine + index;
    const previous = locations.get(key);
    if (previous !== undefined) {
      throw new Error(`screen ${screenId} has duplicate ${key} declarations at lines ${previous} and ${lineNumber}`);
    }
    locations.set(key, lineNumber);
    declarations.set(key, candidate.slice(colon + 1).replace(/^(?:__|[*`])+/, '').trim());
  }
  return declarations;
};

const parseScreenStates = (block: string, screenId: string, declaration: string | undefined): string[] => {
  const explicit = declaration?.replace(/\.$/, '');
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
  // Account for every level-three screen heading, including malformed headings.
  // Matching only valid blocks would silently discard a retired inventory between them.
  // Deeper headings belong to retained per-state sketches within a screen block.
  const headings = [...screensSection.matchAll(/^[\t ]*###(?:[\t ]+[^\n]*)?$/gm)];
  const blocks = headings.map((heading, index) => {
    const match = /^### .+ \(`([^`]+)`\)$/.exec(heading[0]);
    if (!match) {
      throw new Error(`noncanonical Screens detail heading: ${heading[0]}`);
    }
    return {
      id: match[1]!,
      body: screensSection.slice(heading.index! + heading[0].length, headings[index + 1]?.index),
      firstLine: markdown.slice(0, markdown.indexOf(screensSection) + heading.index! + heading[0].length).split('\n').length,
    };
  });
  const summary = screensSection.slice(0, headings[0]?.index);
  const summaryLines = summary.split('\n').filter((line) => line.trim() !== '');
  const header = summaryLines[0] ?? '';
  const headerMatch = /^\| id \| kind \| route \| title \|(?: (url_params|wp_page) \|)?$/.exec(header);
  const fifthColumn = headerMatch?.[1];
  const columnCount = fifthColumn ? 5 : 4;
  if (summaryLines.length > 0 && !headerMatch) {
    throw new Error(`noncanonical Screens table row: ${header}`);
  }
  const separator = summaryLines[1] ?? '';
  if (summaryLines.length > 0 && separator !== `|${' --- |'.repeat(columnCount)}`) {
    throw new Error(`noncanonical Screens table row: ${separator}`);
  }
  const summaries = new Map<
    string,
    Pick<RenderParityMap['screens'][number], 'id' | 'kind' | 'title' | 'route' | 'url_params'>
  >();

  // Every nonblank summary line must belong to the canonical table. In particular,
  // indentation and missing ID backticks must never hide duplicate or orphan rows.
  for (const line of summaryLines.slice(2)) {
    const cells = splitTableRow(line);
    const canonicalRow = `| ${cells.map((cell) => cell.replaceAll('|', '\\|')).join(' | ')} |`;
    if (line !== canonicalRow || cells.length !== columnCount || !/^`[^`]+`$/.test(cells[0] ?? '')) {
      throw new Error(`noncanonical Screens table row: ${line}`);
    }
    const [rawId, kind, rawRoute, title, rawParams = '—'] = cells;
    const id = unquote(rawId ?? '');
    if (summaries.has(id)) {
      throw new Error(`screen ${id} has duplicate Screens table rows: ${line}`);
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

  const detailIds = new Set<string>();
  const screens = blocks.map(({ id, body: block, firstLine }) => {
    if (detailIds.has(id)) {
      throw new Error(`screen ${id} has duplicate detail blocks`);
    }
    detailIds.add(id);
    const base = summaries.get(id);
    if (!base) {
      throw new Error(`screen ${id} has a detail block but no Screens table row`);
    }
    const metadata = scanDeclarations(block, id, firstLine);
    const purpose = metadata.get('Purpose') ?? '';
    const params = metadata.get('url_params');
    const actionStates = metadata.get('Action states');
    const parsedParams = params ? params.split(', ').map(unquote) : base.url_params;
    if (params && fifthColumn === 'url_params' && JSON.stringify(parsedParams) !== JSON.stringify(base.url_params)) {
      throw new Error(`screen ${id} has different url_params in the Screens table and detail block`);
    }
    const zones: RenderParityMap['screens'][number]['zones'] = [];
    const zoneLines: string[] = [];
    let fence: string | undefined;
    let inZoneTable = false;
    for (const line of block.split('\n')) {
      // Screen sketches contain pipe-prefixed rows too; only actual Markdown
      // tables outside fenced code blocks belong to the zone inventory.
      if (fence) {
        const close = /^ {0,3}(`+|~+)[ \t]*$/.exec(line)?.[1];
        if (close && close[0] === fence[0] && close.length >= fence.length) {
          fence = undefined;
        }
        continue;
      }
      const open = /^ {0,3}(`{3,}|~{3,})/.exec(line)?.[1];
      if (open) {
        fence = open;
        inZoneTable = false;
        continue;
      }
      if (!line.trim()) {
        inZoneTable = false;
      } else if (inZoneTable || line.trimStart().startsWith('|')) {
        zoneLines.push(line);
        inZoneTable = true;
      }
    }
    const zoneIds = new Set<string>();
    for (const [index, line] of zoneLines.entries()) {
      if (index < 2) {
        const expected = index === 0 ? '| zone id | label | role | states |' : '| --- | --- | --- | --- |';
        if (line !== expected) {
          throw new Error(`noncanonical Zones table row: ${line}`);
        }
        continue;
      }
      const cells = splitTableRow(line);
      const canonicalRow = `| ${cells.map((cell) => cell.replaceAll('|', '\\|')).join(' | ')} |`;
      if (line !== canonicalRow || cells.length !== 4 || !/^`[^`]+`$/.test(cells[0] ?? '')) {
        throw new Error(`noncanonical Zones table row: ${line}`);
      }
      const [rawZoneId, label, role, rawStates] = cells;
      const zoneId = unquote(rawZoneId ?? '');
      if (zoneIds.has(zoneId)) {
        throw new Error(`zone ${zoneId} has duplicate Zones table rows: ${line}`);
      }
      zoneIds.add(zoneId);
      zones.push({
        id: zoneId,
        label: label ?? '',
        role: role ?? '',
        states: (rawStates ?? '').split(', ').filter(Boolean),
      });
    }
    if (zoneLines.length === 1) {
      throw new Error(`screen ${id} has an incomplete Zones table`);
    }
    return {
      ...base,
      purpose,
      url_params: parsedParams,
      states: parseScreenStates(block, id, metadata.get('Screen states')),
      ...(actionStates
        ? { action_states: actionStates.split(', ') }
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
  const lines = section(markdown, 'Actions')
    .split('\n')
    .filter((line) => line.trim() !== '');
  const header = lines[0] ?? '';
  const headerMatch =
    /^\| id \| verb \| target \| hierarchy \| costly \| irreversible \| preview required \| screen id \|(?: when \(recovery state\) \|)?$/.exec(
      header,
    );
  const columnCount = header.endsWith(' when (recovery state) |') ? 9 : 8;
  if (lines.length > 0 && !headerMatch) {
    throw new Error(`noncanonical Actions table row: ${header}`);
  }
  const separator = lines[1] ?? '';
  if (lines.length > 0 && separator !== `|${' --- |'.repeat(columnCount)}`) {
    throw new Error(`noncanonical Actions table row: ${separator}`);
  }
  const ids = new Set<string>();
  for (const line of lines.slice(2)) {
    const cells = splitTableRow(line);
    const canonicalRow = `| ${cells.map((cell) => cell.replaceAll('|', '\\|')).join(' | ')} |`;
    if (line !== canonicalRow || cells.length !== columnCount || !/^`[^`]+`$/.test(cells[0] ?? '')) {
      throw new Error(`noncanonical Actions table row: ${line}`);
    }
    const [rawId, verb, target, hierarchy, costly, irreversible, previewRequired, rawScreenId, when] = cells;
    const id = unquote(rawId ?? '');
    if (ids.has(id)) {
      throw new Error(`action ${id} has duplicate Actions table rows: ${line}`);
    }
    ids.add(id);
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
  const lines = section(markdown, 'Domain state mapping').split('\n').filter((line) => line.trim() !== '');
  const header = ['| domain state(s) | canonical state |', '| --- | --- |'];
  for (let index = 0; lines.length > 0 && index < header.length; index += 1) {
    if (lines[index] !== header[index]) {
      throw new Error(`noncanonical Domain state mapping table row: ${lines[index] ?? ''}`);
    }
  }
  const seen = new Set<string>();
  for (const line of lines.slice(2)) {
    const match = /^\| (`[^`|]+`(?:, `[^`|]+`)*) \| `([^`|]+)` \|$/.exec(line);
    if (!match) {
      throw new Error(`noncanonical Domain state mapping table row: ${line}`);
    }
    const domainStates = match[1]!.split(', ').map(unquote);
    for (const state of domainStates) {
      if (seen.has(state)) {
        throw new Error(`Domain state mapping has duplicate domain state ${state}: ${line}`);
      }
      seen.add(state);
    }
    mappings.push({
      domain_states: domainStates,
      canonical_state: match[2]!,
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
      for (const state of zone.states ?? []) {
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
    actions: doc.actions.map((action) => ({
      ...action,
      costly: action.costly ?? false,
      irreversible: action.irreversible ?? false,
      preview_required: action.preview_required ?? false,
      screen_id: action.screen_id ?? null,
    })),
    flows: doc.flows.map((flow) => ({
      id: flow.id,
      label: flow.label ?? flow.id,
      job: flow.job,
      steps: flow.steps.map((step) => ({
        screen_id: step.screen_id,
        branch_label: step.branch_label ?? null,
      })),
    })),
    ...(doc.domain_state_mappings?.length ? { domain_state_mappings: doc.domain_state_mappings } : {}),
    ...(doc.slices?.length ? { slices: doc.slices } : {}),
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
