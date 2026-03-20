import type { SubFunction } from './aiService';
import type { FunctionBridgeInfo, FunctionRouteInfo } from '../types/functionFlow';

export interface FrameworkProjectContext {
  summary: string;
  languages: string[];
  allFilePaths: string[];
  codeFilePaths: string[];
}

export interface FrameworkEntryPointHint {
  adapterId: string;
  framework: string;
  entryPoints: string[];
  reason: string;
}

export interface FrameworkEntryBridgeContext extends FrameworkProjectContext {
  owner: string;
  repo: string;
  githubUrl: string;
  entryFilePath: string;
  entryFileContent: string;
  getFileContent: (path: string) => Promise<string>;
}

export interface FrameworkEntryBridgeResult {
  adapterId: string;
  framework: string;
  reason: string;
  rootSummary: string;
  nodes: SubFunction[];
}

interface FrameworkBridgeAdapter {
  id: string;
  framework: string;
  getEntryPointHints?: (
    context: FrameworkProjectContext,
  ) => Promise<FrameworkEntryPointHint | null> | FrameworkEntryPointHint | null;
  buildEntryBridge: (
    context: FrameworkEntryBridgeContext,
  ) => Promise<FrameworkEntryBridgeResult | null> | FrameworkEntryBridgeResult | null;
}

interface SpringControllerEndpoint {
  controllerName: string;
  methodName: string;
  filePath: string;
  route: FunctionRouteInfo;
}

interface PythonRouteEndpoint {
  symbolName: string;
  filePath: string;
  route: FunctionRouteInfo;
  summary: string;
  drillDown?: -1 | 0 | 1;
}

interface PythonImportState {
  moduleAliases: Map<string, string>;
  symbolAliases: Map<string, { module: string; symbol: string }>;
}

interface DjangoViewResolution {
  filePath: string;
  symbolName: string;
  external?: boolean;
}

const JAVA_FILE_REGEX = /\.java$/i;
const PYTHON_FILE_REGEX = /\.py$/i;

const SPRING_ENTRY_PATH_REGEX = /src\/main\/java\/.*(?:Application|Main|Bootstrap|Server)\.java$/i;
const SPRING_BUILD_FILE_REGEX = /(^|\/)(pom\.xml|build\.gradle(?:\.kts)?|settings\.gradle(?:\.kts)?)$/i;
const SPRING_CONTROLLER_PATH_REGEX = /(?:^|\/)(?:controllers?|controller|api|rest|web)(?:\/|$)|Controller\.java$/i;
const SPRING_CONTROLLER_ANNOTATION_REGEX = /@(RestController|Controller)\b/;
const SPRING_MAPPING_ANNOTATION_REGEX = /@(Get|Post|Put|Delete|Patch|Request)Mapping\b/;
const JAVA_CONTROL_KEYWORDS = new Set([
  'if',
  'for',
  'while',
  'switch',
  'catch',
  'return',
  'throw',
  'new',
  'else',
  'case',
  'do',
  'try',
  'synchronized',
]);

const SPRING_BOOT_ADAPTER_ID = 'java-springboot';
const SPRING_BOOT_FRAMEWORK = 'Spring Boot';

const PYTHON_FLASK_ADAPTER_ID = 'python-flask';
const PYTHON_FLASK_FRAMEWORK = 'Flask';
const PYTHON_FASTAPI_ADAPTER_ID = 'python-fastapi';
const PYTHON_FASTAPI_FRAMEWORK = 'FastAPI';
const PYTHON_DJANGO_ADAPTER_ID = 'python-django';
const PYTHON_DJANGO_FRAMEWORK = 'Django';

const PYTHON_WEB_ENTRY_PATH_REGEX = /(?:^|\/)(?:app|main|run|server|application|manage|wsgi|asgi)\.py$/i;
const PYTHON_WSGI_ENTRY_PATH_REGEX = /(?:^|\/)wsgi\.py$/i;
const PYTHON_ASGI_ENTRY_PATH_REGEX = /(?:^|\/)asgi\.py$/i;
const DJANGO_URLS_PATH_REGEX = /(?:^|\/)urls\.py$/i;

const FLASK_MARKER_REGEX = /\bfrom\s+flask\s+import\b|\bimport\s+flask\b|\bFlask\s*\(|\bBlueprint\s*\(/;
const FASTAPI_MARKER_REGEX = /\bfrom\s+fastapi\s+import\b|\bimport\s+fastapi\b|\bFastAPI\s*\(|\bAPIRouter\s*\(/;
const DJANGO_MARKER_REGEX = /\bfrom\s+django\b|\bimport\s+django\b|\bget_wsgi_application\s*\(|\bexecute_from_command_line\s*\(/;

function dedupeStrings(values: string[]) {
  return [...new Set(values.filter(Boolean))];
}

function countChars(value: string, char: string) {
  return value.split(char).length - 1;
}

function countBraceDelta(value: string) {
  return countChars(value, '{') - countChars(value, '}');
}

function countBraceDeltaInRange(lines: string[], startIndex: number, endIndex: number) {
  let delta = 0;
  for (let index = startIndex; index <= endIndex; index += 1) {
    delta += countBraceDelta(lines[index] || '');
  }
  return delta;
}

function getIndent(line: string): number {
  const expanded = line.replace(/\t/g, '    ');
  return expanded.length - expanded.trimStart().length;
}

function normalizeRoutePath(path: string) {
  if (!path) {
    return '/';
  }

  const normalized = path.replace(/\/{2,}/g, '/');
  if (normalized === '/') {
    return normalized;
  }

  return normalized.endsWith('/') ? normalized.slice(0, -1) : normalized;
}

function joinRoutePath(basePath: string, methodPath: string) {
  const normalizedBase = basePath ? `/${basePath}`.replace(/\/{2,}/g, '/') : '';
  const normalizedMethod = methodPath ? `/${methodPath}`.replace(/\/{2,}/g, '/') : '';
  return normalizeRoutePath(`${normalizedBase}${normalizedMethod}` || '/');
}

function buildRouteInfo(path: string, methods: string[] | undefined, source: string): FunctionRouteInfo {
  const normalizedMethods = dedupeStrings((methods || []).map((method) => method.toUpperCase()));
  return {
    path: normalizeRoutePath(path || '/'),
    methods: normalizedMethods.length ? normalizedMethods : undefined,
    source,
  };
}

function buildMultiPathRouteInfo(paths: string[], methods: string[] | undefined, source: string): FunctionRouteInfo {
  const normalizedPaths = dedupeStrings(paths.map((path) => normalizeRoutePath(path || '/')));
  return {
    path: normalizedPaths.join(' | '),
    methods: methods?.length ? dedupeStrings(methods.map((method) => method.toUpperCase())) : undefined,
    source,
  };
}

function splitTopLevelArgs(value: string): string[] {
  const args: string[] = [];
  let current = '';
  let parentheses = 0;
  let brackets = 0;
  let braces = 0;
  let quote = '';

  for (let index = 0; index < value.length; index += 1) {
    const char = value[index];
    const previous = value[index - 1];

    if (quote) {
      current += char;
      if (char === quote && previous !== '\\') {
        quote = '';
      }
      continue;
    }

    if (char === '"' || char === '\'') {
      quote = char;
      current += char;
      continue;
    }

    if (char === '(') {
      parentheses += 1;
    } else if (char === ')') {
      parentheses -= 1;
    } else if (char === '[') {
      brackets += 1;
    } else if (char === ']') {
      brackets -= 1;
    } else if (char === '{') {
      braces += 1;
    } else if (char === '}') {
      braces -= 1;
    } else if (char === ',' && parentheses === 0 && brackets === 0 && braces === 0) {
      if (current.trim()) {
        args.push(current.trim());
      }
      current = '';
      continue;
    }

    current += char;
  }

  if (current.trim()) {
    args.push(current.trim());
  }

  return args;
}

function extractNamedArgumentValue(args: string[], name: string) {
  const targetPrefix = `${name}=`;
  for (const arg of args) {
    const compact = arg.replace(/\s+/g, '');
    if (compact.startsWith(targetPrefix)) {
      return arg.slice(arg.indexOf('=') + 1).trim();
    }
  }

  return '';
}

function parsePythonStringLiterals(value: string) {
  const matches = value.match(/(?:[rubf]|br|rb|fr|rf)?(?:"([^"\\]*(?:\\.[^"\\]*)*)"|'([^'\\]*(?:\\.[^'\\]*)*)')/gi) || [];
  return matches
    .map((item) => {
      const quoteIndex = item.indexOf('"') >= 0 ? item.indexOf('"') : item.indexOf('\'');
      const quote = item[quoteIndex];
      const start = quoteIndex + 1;
      const end = item.lastIndexOf(quote);
      return end > start ? item.slice(start, end) : '';
    })
    .filter(Boolean);
}

function parsePythonStringLiteral(value: string) {
  return parsePythonStringLiterals(value)[0] || '';
}

function parsePythonMethodsArg(value: string) {
  return dedupeStrings(parsePythonStringLiterals(value).map((item) => item.toUpperCase()));
}

function consumeParenthesizedExpression(content: string, openIndex: number) {
  let depth = 0;
  let quote = '';

  for (let index = openIndex; index < content.length; index += 1) {
    const char = content[index];
    const previous = content[index - 1];

    if (quote) {
      if (char === quote && previous !== '\\') {
        quote = '';
      }
      continue;
    }

    if (char === '"' || char === '\'') {
      quote = char;
      continue;
    }

    if (char === '(') {
      depth += 1;
    } else if (char === ')') {
      depth -= 1;
      if (depth === 0) {
        return index;
      }
    }
  }

  return -1;
}

function getCallBody(callExpression: string) {
  const openIndex = callExpression.indexOf('(');
  const closeIndex = callExpression.lastIndexOf(')');
  if (openIndex === -1 || closeIndex === -1 || closeIndex <= openIndex) {
    return '';
  }

  return callExpression.slice(openIndex + 1, closeIndex).trim();
}

function extractCallExpressions(content: string, callNames: string[]) {
  const expressions: string[] = [];
  const regex = new RegExp(`\\b(?:${callNames.join('|')})\\s*\\(`, 'g');
  let match: RegExpExecArray | null;

  while ((match = regex.exec(content)) !== null) {
    const openIndex = content.indexOf('(', match.index);
    if (openIndex === -1) {
      continue;
    }

    const closeIndex = consumeParenthesizedExpression(content, openIndex);
    if (closeIndex === -1) {
      continue;
    }

    expressions.push(content.slice(match.index, closeIndex + 1));
    regex.lastIndex = closeIndex + 1;
  }

  return expressions;
}

function consumePythonStatement(lines: string[], startIndex: number) {
  let endIndex = startIndex;
  let text = lines[startIndex].trim();
  let balance =
    countChars(text, '(') - countChars(text, ')') +
    countChars(text, '[') - countChars(text, ']') +
    countChars(text, '{') - countChars(text, '}');
  let continuation = /\\\s*$/.test(lines[startIndex]);

  while ((balance > 0 || continuation) && endIndex < lines.length - 1) {
    endIndex += 1;
    const nextLine = lines[endIndex].trim();
    text = `${text}\n${nextLine}`;
    balance +=
      countChars(nextLine, '(') - countChars(nextLine, ')') +
      countChars(nextLine, '[') - countChars(nextLine, ']') +
      countChars(nextLine, '{') - countChars(nextLine, '}');
    continuation = /\\\s*$/.test(lines[endIndex]);
  }

  return { text, endIndex };
}

function getDirectory(path: string) {
  const lastSlash = path.lastIndexOf('/');
  return lastSlash === -1 ? '' : path.slice(0, lastSlash);
}

function getBaseName(path: string) {
  const lastSlash = path.lastIndexOf('/');
  return lastSlash === -1 ? path : path.slice(lastSlash + 1);
}

function isLikelyPythonProject(context: FrameworkProjectContext) {
  return (
    context.languages.some((language) => /python/i.test(language)) ||
    context.codeFilePaths.some((path) => PYTHON_FILE_REGEX.test(path))
  );
}

function isPythonWebEntryPath(path: string) {
  return PYTHON_WEB_ENTRY_PATH_REGEX.test(path);
}

function isPythonWsgiEntryFile(entryFilePath: string, entryFileContent: string) {
  return (
    PYTHON_WSGI_ENTRY_PATH_REGEX.test(entryFilePath) ||
    /\bget_wsgi_application\s*\(/.test(entryFileContent) ||
    /\bmake_server\s*\(/.test(entryFileContent) ||
    /\brun_simple\s*\(/.test(entryFileContent) ||
    /\bWSGIHandler\b/.test(entryFileContent)
  );
}

function isLikelyPythonWebEntryFile(entryFilePath: string, entryFileContent: string) {
  return (
    isPythonWebEntryPath(entryFilePath) ||
    isPythonWsgiEntryFile(entryFilePath, entryFileContent) ||
    PYTHON_ASGI_ENTRY_PATH_REGEX.test(entryFilePath)
  );
}

function scorePythonEntryPath(path: string) {
  const baseName = getBaseName(path).toLowerCase();
  let score = 0;

  if (baseName === 'manage.py') {
    score += 320;
  } else if (baseName === 'wsgi.py') {
    score += 300;
  } else if (baseName === 'asgi.py') {
    score += 280;
  } else if (['app.py', 'main.py', 'run.py', 'server.py', 'application.py'].includes(baseName)) {
    score += 240;
  }

  if (path.includes('/src/')) {
    score += 20;
  }

  if (path.includes('/app/')) {
    score += 20;
  }

  return score;
}

function pickPythonEntryPointCandidates(context: FrameworkProjectContext, matcher?: (path: string) => boolean) {
  return dedupeStrings(
    context.codeFilePaths
      .filter((path) => PYTHON_FILE_REGEX.test(path))
      .filter((path) => (matcher ? matcher(path) : isPythonWebEntryPath(path)))
      .map((path) => ({ path, score: scorePythonEntryPath(path) }))
      .filter((entry) => entry.score > 0)
      .sort((left, right) => {
        if (left.score !== right.score) {
          return right.score - left.score;
        }
        return left.path.localeCompare(right.path);
      })
      .map((entry) => entry.path),
  ).slice(0, 12);
}

function scorePythonRoutePath(path: string, entryFilePath = '') {
  const baseName = getBaseName(path).toLowerCase();
  let score = 0;

  if (!PYTHON_FILE_REGEX.test(path)) {
    return score;
  }

  if (path === entryFilePath) {
    score += 220;
  }

  if (getDirectory(path) === getDirectory(entryFilePath)) {
    score += 90;
  }

  if (DJANGO_URLS_PATH_REGEX.test(path)) {
    score += 260;
  }

  if (/(?:^|\/)(?:views?|routes?|routers?|api|endpoints?|controllers?)(?:\/|$)/i.test(path)) {
    score += 180;
  }

  if (['app.py', 'main.py', 'server.py', 'routes.py', 'router.py', 'urls.py', 'views.py'].includes(baseName)) {
    score += 150;
  }

  return score;
}

function pickPythonRouteCandidates(context: FrameworkProjectContext, entryFilePath = '') {
  const pythonFiles = context.codeFilePaths.filter((path) => PYTHON_FILE_REGEX.test(path));
  if (pythonFiles.length <= 180) {
    return pythonFiles.sort((left, right) => left.localeCompare(right));
  }

  return pythonFiles
    .map((path) => ({ path, score: scorePythonRoutePath(path, entryFilePath) }))
    .sort((left, right) => {
      if (left.score !== right.score) {
        return right.score - left.score;
      }
      return left.path.localeCompare(right.path);
    })
    .map((entry) => entry.path)
    .slice(0, 180);
}

async function loadFileBatch(paths: string[], getFileContent: (path: string) => Promise<string>) {
  const loaded = await Promise.all(
    paths.map(async (path) => {
      try {
        return {
          path,
          content: await getFileContent(path),
        };
      } catch {
        return null;
      }
    }),
  );

  return loaded.filter((entry): entry is { path: string; content: string } => Boolean(entry));
}

function buildRouteHandlerSubFunction(
  endpoint: PythonRouteEndpoint,
  adapterId: string,
  framework: string,
  bridgeReason: string,
): SubFunction {
  const bridge: FunctionBridgeInfo = {
    adapterId,
    framework,
    kind: 'handler',
    reason: bridgeReason,
  };

  return {
    name: endpoint.symbolName,
    filePath: endpoint.filePath,
    summary: endpoint.summary,
    drillDown: endpoint.drillDown ?? 1,
    route: endpoint.route,
    bridge,
  };
}

function dedupePythonEndpoints(endpoints: PythonRouteEndpoint[]) {
  const seen = new Set<string>();
  return endpoints.filter((endpoint) => {
    const key = [
      endpoint.filePath,
      endpoint.symbolName,
      endpoint.route.path,
      endpoint.route.methods?.join(',') || '',
    ].join('|');
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function parsePythonDecoratorSignature(decorator: string) {
  const compact = decorator.trim();
  const match = compact.match(/^@([A-Za-z_][A-Za-z0-9_\.]*)\s*(?:\(([\s\S]*)\))?$/);
  if (!match) {
    return null;
  }

  return {
    name: match[1],
    argsText: (match[2] || '').trim(),
  };
}

function parsePythonRoutePathFromArgs(argsText: string, namedKeys: string[]) {
  const args = splitTopLevelArgs(argsText);
  const firstLiteral = parsePythonStringLiteral(args[0] || '');
  if (firstLiteral) {
    return firstLiteral;
  }

  for (const key of namedKeys) {
    const value = extractNamedArgumentValue(args, key);
    const literal = parsePythonStringLiteral(value);
    if (literal) {
      return literal;
    }
  }

  return '';
}

function parseFlaskBlueprintPrefixes(content: string) {
  const prefixes = new Map<string, string[]>();
  const lines = content.split(/\r?\n/);

  for (let index = 0; index < lines.length; index += 1) {
    const statement = consumePythonStatement(lines, index);
    const match = statement.text.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*Blueprint\s*\(([\s\S]*)\)\s*$/);
    if (!match) {
      index = statement.endIndex;
      continue;
    }

    const args = splitTopLevelArgs(match[2]);
    const prefix = parsePythonStringLiteral(extractNamedArgumentValue(args, 'url_prefix'));
    prefixes.set(match[1], [prefix || '']);
    index = statement.endIndex;
  }

  return prefixes;
}

function parseFastApiRouterPrefixes(content: string) {
  const prefixes = new Map<string, string[]>();
  const lines = content.split(/\r?\n/);

  for (let index = 0; index < lines.length; index += 1) {
    const statement = consumePythonStatement(lines, index);
    const routerMatch = statement.text.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*APIRouter\s*\(([\s\S]*)\)\s*$/);
    if (routerMatch) {
      const args = splitTopLevelArgs(routerMatch[2]);
      const prefix = parsePythonStringLiteral(extractNamedArgumentValue(args, 'prefix'));
      prefixes.set(routerMatch[1], [prefix || '']);
      index = statement.endIndex;
      continue;
    }

    const includeMatch = statement.text.match(/^[A-Za-z_][A-Za-z0-9_\.]*\s*\.\s*include_router\s*\(([\s\S]*)\)\s*$/);
    if (includeMatch) {
      const args = splitTopLevelArgs(includeMatch[1]);
      const routerName = (args[0] || '').trim();
      const includePrefix = parsePythonStringLiteral(extractNamedArgumentValue(args, 'prefix'));
      if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(routerName) && includePrefix) {
        const existingPrefixes = prefixes.get(routerName) || [''];
        prefixes.set(
          routerName,
          dedupeStrings(existingPrefixes.map((prefix) => joinRoutePath(includePrefix, prefix))),
        );
      }
      index = statement.endIndex;
      continue;
    }

    index = statement.endIndex;
  }

  return prefixes;
}

function parseFlaskDecoratorRoute(pendingDecorators: string[], blueprintPrefixes: Map<string, string[]>) {
  const paths: string[] = [];
  const methods: string[] = [];

  for (const decorator of pendingDecorators) {
    const signature = parsePythonDecoratorSignature(decorator);
    if (!signature) {
      continue;
    }

    const segments = signature.name.split('.');
    if (segments.length < 2) {
      continue;
    }

    const receiver = segments.slice(0, -1).join('.');
    const action = segments[segments.length - 1].toLowerCase();
    if (!['route', 'get', 'post', 'put', 'delete', 'patch'].includes(action)) {
      continue;
    }

    const routePath = parsePythonRoutePathFromArgs(signature.argsText, ['rule', 'path']);
    const receiverPrefixes = blueprintPrefixes.get(receiver) || [''];
    paths.push(...receiverPrefixes.map((prefix) => joinRoutePath(prefix, routePath)));

    if (action === 'route') {
      const args = splitTopLevelArgs(signature.argsText);
      const explicitMethods = parsePythonMethodsArg(extractNamedArgumentValue(args, 'methods'));
      methods.push(...(explicitMethods.length ? explicitMethods : ['GET']));
    } else {
      methods.push(action.toUpperCase());
    }
  }

  if (!paths.length) {
    return null;
  }

  return buildMultiPathRouteInfo(paths, methods, 'flask-route');
}

function parseFastApiDecoratorRoute(pendingDecorators: string[], routerPrefixes: Map<string, string[]>) {
  const paths: string[] = [];
  const methods: string[] = [];

  for (const decorator of pendingDecorators) {
    const signature = parsePythonDecoratorSignature(decorator);
    if (!signature) {
      continue;
    }

    const segments = signature.name.split('.');
    if (segments.length < 2) {
      continue;
    }

    const receiver = segments.slice(0, -1).join('.');
    const action = segments[segments.length - 1].toLowerCase();
    if (!['get', 'post', 'put', 'delete', 'patch', 'options', 'head', 'trace', 'api_route', 'websocket'].includes(action)) {
      continue;
    }

    const routePath = parsePythonRoutePathFromArgs(signature.argsText, ['path']);
    const receiverPrefixes = routerPrefixes.get(receiver) || [''];
    paths.push(...receiverPrefixes.map((prefix) => joinRoutePath(prefix, routePath)));

    if (action === 'api_route') {
      const args = splitTopLevelArgs(signature.argsText);
      const explicitMethods = parsePythonMethodsArg(extractNamedArgumentValue(args, 'methods'));
      methods.push(...(explicitMethods.length ? explicitMethods : ['GET']));
    } else if (action === 'websocket') {
      methods.push('WS');
    } else {
      methods.push(action.toUpperCase());
    }
  }

  if (!paths.length) {
    return null;
  }

  return buildMultiPathRouteInfo(paths, methods, 'fastapi-route');
}

function extractPythonDecoratedRoutes(
  filePath: string,
  content: string,
  parseRoute: (pendingDecorators: string[]) => FunctionRouteInfo | null,
  summaryPrefix: string,
): PythonRouteEndpoint[] {
  const lines = content.split(/\r?\n/);
  const endpoints: PythonRouteEndpoint[] = [];
  const pendingDecorators: string[] = [];
  const classStack: Array<{ name: string; indent: number }> = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    const indent = getIndent(line);

    while (classStack.length > 0 && indent <= classStack[classStack.length - 1].indent && trimmed) {
      classStack.pop();
    }

    if (!trimmed || trimmed.startsWith('#')) {
      if (!trimmed) {
        pendingDecorators.length = 0;
      }
      continue;
    }

    if (trimmed.startsWith('@')) {
      const decorator = consumePythonStatement(lines, index);
      pendingDecorators.push(decorator.text);
      index = decorator.endIndex;
      continue;
    }

    const classMatch = trimmed.match(/^class\s+([A-Za-z_][A-Za-z0-9_]*)\b[^\n:]*:/);
    if (classMatch) {
      classStack.push({ name: classMatch[1], indent });
      pendingDecorators.length = 0;
      continue;
    }

    const functionMatch = trimmed.match(/^(?:async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/);
    if (functionMatch) {
      const route = parseRoute(pendingDecorators);
      if (route) {
        const ownerName = classStack[classStack.length - 1]?.name;
        const symbolName = ownerName ? `${ownerName}.${functionMatch[1]}` : functionMatch[1];
        endpoints.push({
          symbolName,
          filePath,
          route,
          summary: `${summaryPrefix}，负责响应 ${route.path}`,
          drillDown: 1,
        });
      }
      pendingDecorators.length = 0;
      continue;
    }

    pendingDecorators.length = 0;
  }

  return endpoints;
}

function hasFlaskMarkers(content: string) {
  return FLASK_MARKER_REGEX.test(content);
}

function hasFastApiMarkers(content: string) {
  return FASTAPI_MARKER_REGEX.test(content);
}

function hasDjangoMarkers(content: string) {
  return DJANGO_MARKER_REGEX.test(content);
}

async function collectFlaskEndpoints(context: FrameworkEntryBridgeContext) {
  const routeCandidates = pickPythonRouteCandidates(context, context.entryFilePath);
  const routeFiles = await loadFileBatch(routeCandidates, context.getFileContent);
  const relevantFiles = routeFiles.filter((entry) => hasFlaskMarkers(entry.content) || /@[A-Za-z_][A-Za-z0-9_\.]*\.(?:route|get|post|put|delete|patch)\s*\(/.test(entry.content));

  const endpoints = relevantFiles.flatMap((entry) => {
    const blueprintPrefixes = parseFlaskBlueprintPrefixes(entry.content);
    return extractPythonDecoratedRoutes(
      entry.path,
      entry.content,
      (pendingDecorators) => parseFlaskDecoratorRoute(pendingDecorators, blueprintPrefixes),
      'Flask 路由响应函数',
    );
  });

  return dedupePythonEndpoints(endpoints);
}

async function collectFastApiEndpoints(context: FrameworkEntryBridgeContext) {
  const routeCandidates = pickPythonRouteCandidates(context, context.entryFilePath);
  const routeFiles = await loadFileBatch(routeCandidates, context.getFileContent);
  const relevantFiles = routeFiles.filter((entry) => hasFastApiMarkers(entry.content) || /@[A-Za-z_][A-Za-z0-9_\.]*\.(?:get|post|put|delete|patch|options|head|trace|api_route|websocket)\s*\(/.test(entry.content));

  const endpoints = relevantFiles.flatMap((entry) => {
    const routerPrefixes = parseFastApiRouterPrefixes(entry.content);
    return extractPythonDecoratedRoutes(
      entry.path,
      entry.content,
      (pendingDecorators) => parseFastApiDecoratorRoute(pendingDecorators, routerPrefixes),
      'FastAPI 路由响应函数',
    );
  });

  return dedupePythonEndpoints(endpoints);
}

function toPythonModulePath(filePath: string) {
  return filePath
    .replace(/\.py$/i, '')
    .replace(/\/__init__$/i, '')
    .replace(/\//g, '.');
}

function getPythonPackageName(filePath: string) {
  const modulePath = toPythonModulePath(filePath);
  const directory = getDirectory(modulePath.replace(/\./g, '/')).replace(/\//g, '.');
  return directory || modulePath;
}

function resolveRelativePythonModule(filePath: string, rawModule: string) {
  if (!rawModule.startsWith('.')) {
    return rawModule;
  }

  const dots = rawModule.match(/^\.+/)?.[0].length || 0;
  const remainder = rawModule.slice(dots);
  const packageSegments = getPythonPackageName(filePath).split('.').filter(Boolean);
  const upCount = Math.max(0, dots - 1);
  const baseSegments = packageSegments.slice(0, Math.max(0, packageSegments.length - upCount));
  const remainderSegments = remainder.split('.').filter(Boolean);
  return [...baseSegments, ...remainderSegments].join('.');
}

function resolvePythonModulePath(modulePath: string, codeFileSet: Set<string>) {
  const candidate = modulePath.replace(/\./g, '/');
  const moduleFile = `${candidate}.py`;
  if (codeFileSet.has(moduleFile)) {
    return moduleFile;
  }

  const initFile = `${candidate}/__init__.py`;
  if (codeFileSet.has(initFile)) {
    return initFile;
  }

  return '';
}

function parsePythonImportState(filePath: string, content: string): PythonImportState {
  const moduleAliases = new Map<string, string>();
  const symbolAliases = new Map<string, { module: string; symbol: string }>();
  const lines = content.split(/\r?\n/);

  for (let index = 0; index < lines.length; index += 1) {
    const statement = consumePythonStatement(lines, index);
    const trimmed = statement.text.trim();

    const importMatch = trimmed.match(/^import\s+(.+)$/);
    if (importMatch) {
      for (const item of splitTopLevelArgs(importMatch[1])) {
        const aliasMatch = item.trim().match(/^([A-Za-z_][A-Za-z0-9_\.]*)\s+as\s+([A-Za-z_][A-Za-z0-9_]*)$/);
        if (aliasMatch) {
          moduleAliases.set(aliasMatch[2], aliasMatch[1]);
          continue;
        }

        const modulePath = item.trim();
        const alias = modulePath.split('.')[0];
        if (alias) {
          moduleAliases.set(alias, alias);
        }
      }
      index = statement.endIndex;
      continue;
    }

    const fromMatch = trimmed.match(/^from\s+([A-Za-z_\.]+)\s+import\s+(.+)$/);
    if (fromMatch) {
      const resolvedModule = resolveRelativePythonModule(filePath, fromMatch[1]);
      for (const item of splitTopLevelArgs(fromMatch[2])) {
        const aliasMatch = item.trim().match(/^([A-Za-z_][A-Za-z0-9_]*)\s+as\s+([A-Za-z_][A-Za-z0-9_]*)$/);
        const symbol = aliasMatch?.[1] || item.trim();
        const alias = aliasMatch?.[2] || symbol;
        if (!symbol || symbol === '*') {
          continue;
        }

        moduleAliases.set(alias, [resolvedModule, symbol].filter(Boolean).join('.'));
        symbolAliases.set(alias, { module: resolvedModule, symbol });
      }
      index = statement.endIndex;
      continue;
    }

    index = statement.endIndex;
  }

  return { moduleAliases, symbolAliases };
}

function normalizeDjangoRouteFragment(routeFragment: string) {
  return routeFragment
    .replace(/^\^+/, '')
    .replace(/\$+$/, '')
    .replace(/^\/+/, '');
}

function resolveDjangoIncludeModule(
  includeExpression: string,
  importState: PythonImportState,
  currentFilePath: string,
) {
  const body = getCallBody(includeExpression);
  const args = splitTopLevelArgs(body);
  const firstArg = (args[0] || '').trim();
  const literalModule = parsePythonStringLiteral(firstArg);
  if (literalModule) {
    return literalModule;
  }

  if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(firstArg)) {
    return importState.moduleAliases.get(firstArg) || '';
  }

  const segments = firstArg.split('.').filter(Boolean);
  if (!segments.length) {
    return '';
  }

  const aliasModule = importState.moduleAliases.get(segments[0]);
  if (aliasModule) {
    return [aliasModule, ...segments.slice(1)].join('.');
  }

  if (firstArg.startsWith('.')) {
    return resolveRelativePythonModule(currentFilePath, firstArg);
  }

  return firstArg;
}

function resolvePythonReferenceToFile(
  expression: string,
  importState: PythonImportState,
  currentFilePath: string,
  codeFileSet: Set<string>,
): DjangoViewResolution | null {
  const target = expression.trim();
  if (!target || /\blambda\b/.test(target)) {
    return null;
  }

  const directSymbol = importState.symbolAliases.get(target);
  if (directSymbol) {
    const filePath = resolvePythonModulePath(directSymbol.module, codeFileSet);
    return filePath
      ? { filePath, symbolName: directSymbol.symbol }
      : { filePath: '', symbolName: directSymbol.symbol, external: true };
  }

  const segments = target.split('.').filter(Boolean);
  if (!segments.length) {
    return null;
  }

  if (segments.length >= 2) {
    const modulePath = segments.slice(0, -1).join('.');
    const filePath = resolvePythonModulePath(modulePath, codeFileSet);
    if (filePath) {
      return {
        filePath,
        symbolName: segments[segments.length - 1],
      };
    }
  }

  const aliasModule = importState.moduleAliases.get(segments[0]);
  if (aliasModule) {
    const filePath = resolvePythonModulePath(aliasModule, codeFileSet);
    if (!filePath) {
      return { filePath: '', symbolName: segments.slice(1).join('.') || segments[0], external: true };
    }
    return {
      filePath,
      symbolName: segments.slice(1).join('.') || segments[0],
    };
  }

  if (target.startsWith('.')) {
    const modulePath = resolveRelativePythonModule(currentFilePath, target);
    const filePath = resolvePythonModulePath(modulePath, codeFileSet);
    if (filePath) {
      return { filePath, symbolName: segments[segments.length - 1] || target };
    }
  }

  return null;
}

function resolveDjangoViewReference(
  expression: string,
  importState: PythonImportState,
  currentFilePath: string,
  codeFileSet: Set<string>,
): DjangoViewResolution | null {
  const target = expression.trim();
  if (!target || /\binclude\s*\(/.test(target)) {
    return null;
  }

  const classViewMatch = target.match(/^(.*)\.as_view\s*\(([\s\S]*)\)\s*$/);
  if (classViewMatch) {
    const classTarget = classViewMatch[1].trim();
    const resolvedClass = resolvePythonReferenceToFile(classTarget, importState, currentFilePath, codeFileSet);
    if (!resolvedClass) {
      return null;
    }
    return {
      filePath: resolvedClass.filePath,
      symbolName: classTarget.split('.').pop() || resolvedClass.symbolName,
      external: resolvedClass.external,
    };
  }

  return resolvePythonReferenceToFile(target, importState, currentFilePath, codeFileSet);
}

function guessDjangoRootUrlFiles(context: FrameworkEntryBridgeContext) {
  const rootUrls = new Set<string>();
  const settingsMatch = context.entryFileContent.match(/DJANGO_SETTINGS_MODULE['"]?\s*,\s*['"]([A-Za-z0-9_\.]+)['"]/);
  if (settingsMatch?.[1]) {
    const settingsModule = settingsMatch[1];
    const packageName = settingsModule.replace(/\.settings$/, '');
    const packageUrlFile = packageName ? `${packageName.replace(/\./g, '/')}/urls.py` : '';
    if (packageUrlFile && context.codeFilePaths.includes(packageUrlFile)) {
      rootUrls.add(packageUrlFile);
    }
  }

  for (const path of context.codeFilePaths.filter((filePath) => DJANGO_URLS_PATH_REGEX.test(filePath))) {
    if (/\/site-packages\//i.test(path)) {
      continue;
    }
    rootUrls.add(path);
  }

  return [...rootUrls].sort((left, right) => left.localeCompare(right));
}

async function collectDjangoEndpoints(context: FrameworkEntryBridgeContext) {
  const codeFileSet = new Set(context.codeFilePaths);
  const contentCache = new Map<string, string>();
  const visited = new Set<string>();
  const rootUrlFiles = guessDjangoRootUrlFiles(context);

  const loadContent = async (path: string) => {
    const cached = contentCache.get(path);
    if (cached !== undefined) {
      return cached;
    }
    const content = await context.getFileContent(path);
    contentCache.set(path, content);
    return content;
  };

  const visitUrlFile = async (filePath: string, prefix = ''): Promise<PythonRouteEndpoint[]> => {
    const visitKey = `${filePath}|${prefix}`;
    if (visited.has(visitKey) || !filePath) {
      return [];
    }
    visited.add(visitKey);

    let content = '';
    try {
      content = await loadContent(filePath);
    } catch {
      return [];
    }

    const importState = parsePythonImportState(filePath, content);
    const expressions = extractCallExpressions(content, ['path', 're_path']);
    const endpoints: PythonRouteEndpoint[] = [];

    for (const expression of expressions) {
      const args = splitTopLevelArgs(getCallBody(expression));
      if (args.length < 2) {
        continue;
      }

      const routeFragment = normalizeDjangoRouteFragment(parsePythonStringLiteral(args[0] || ''));
      const fullRoute = joinRoutePath(prefix, routeFragment);
      const targetArg = (args[1] || '').trim();

      if (/\binclude\s*\(/.test(targetArg)) {
        const includeModule = resolveDjangoIncludeModule(targetArg, importState, filePath);
        const includeFilePath = resolvePythonModulePath(includeModule, codeFileSet);
        if (includeFilePath) {
          endpoints.push(...await visitUrlFile(includeFilePath, fullRoute));
        }
        continue;
      }

      const resolvedView = resolveDjangoViewReference(targetArg, importState, filePath, codeFileSet);
      if (!resolvedView || resolvedView.external || !resolvedView.filePath) {
        continue;
      }

      endpoints.push({
        symbolName: resolvedView.symbolName,
        filePath: resolvedView.filePath,
        route: buildRouteInfo(fullRoute, undefined, 'django-urlconf'),
        summary: `Django 路由响应函数，负责响应 ${normalizeRoutePath(fullRoute)}`,
        drillDown: 1,
      });
    }

    return endpoints;
  };

  const endpoints = (await Promise.all(rootUrlFiles.map((filePath) => visitUrlFile(filePath))))
    .flat();

  return dedupePythonEndpoints(endpoints);
}

function isLikelySpringBootProject(context: FrameworkProjectContext) {
  const hasJava =
    context.languages.some((language) => /java/i.test(language)) ||
    context.codeFilePaths.some((path) => JAVA_FILE_REGEX.test(path));
  const hasStandardLayout = context.codeFilePaths.some((path) => path.includes('src/main/java/'));
  const hasBuildFile = context.allFilePaths.some((path) => SPRING_BUILD_FILE_REGEX.test(path));

  return hasJava && (hasStandardLayout || hasBuildFile);
}

function isLikelySpringBootEntryFile(entryFilePath: string, entryFileContent: string) {
  return (
    JAVA_FILE_REGEX.test(entryFilePath) &&
    (
      /@SpringBootApplication\b/.test(entryFileContent) ||
      /\bSpringApplication\s*\.\s*run\s*\(/.test(entryFileContent)
    )
  );
}

function scoreSpringControllerPath(path: string) {
  let score = 0;

  if (!JAVA_FILE_REGEX.test(path)) {
    return score;
  }

  if (path.includes('src/main/java/')) {
    score += 25;
  }

  if (SPRING_CONTROLLER_PATH_REGEX.test(path)) {
    score += 160;
  }

  if (/Controller\.java$/i.test(path)) {
    score += 60;
  }

  if (/(?:^|\/)(api|rest|web)(?:\/|$)/i.test(path)) {
    score += 40;
  }

  return score;
}

function pickSpringEntryPointCandidates(context: FrameworkProjectContext) {
  return dedupeStrings(
    context.codeFilePaths
      .filter((path) => SPRING_ENTRY_PATH_REGEX.test(path))
      .sort((left, right) => left.localeCompare(right)),
  ).slice(0, 8);
}

function pickSpringControllerCandidates(context: FrameworkProjectContext) {
  const scored = context.codeFilePaths
    .filter((path) => JAVA_FILE_REGEX.test(path))
    .map((path) => ({ path, score: scoreSpringControllerPath(path) }))
    .filter((entry) => entry.score > 0)
    .sort((left, right) => {
      if (left.score !== right.score) {
        return right.score - left.score;
      }
      return left.path.localeCompare(right.path);
    })
    .map((entry) => entry.path);

  if (scored.length > 0) {
    return dedupeStrings(scored).slice(0, 120);
  }

  return dedupeStrings(
    context.codeFilePaths.filter(
      (path) => JAVA_FILE_REGEX.test(path) && path.includes('src/main/java/'),
    ),
  ).slice(0, 80);
}

function consumeAnnotation(lines: string[], startIndex: number) {
  let endIndex = startIndex;
  let text = lines[startIndex].trim();
  let balance = countChars(text, '(') - countChars(text, ')');

  while (balance > 0 && endIndex < lines.length - 1) {
    endIndex += 1;
    const nextLine = lines[endIndex].trim();
    text = `${text}\n${nextLine}`;
    balance += countChars(nextLine, '(') - countChars(nextLine, ')');
  }

  return { text, endIndex };
}

function consumeDeclarationHeader(lines: string[], startIndex: number) {
  let endIndex = startIndex;
  let header = lines[startIndex].trim();

  while (
    endIndex < lines.length - 1 &&
    !/[;{]\s*$/.test(lines[endIndex].trim()) &&
    !lines[endIndex].trim().startsWith('@')
  ) {
    endIndex += 1;
    header = `${header} ${lines[endIndex].trim()}`.trim();
  }

  return { header, endIndex };
}

function parseJavaStringLiterals(value: string) {
  const matches = value.match(/"([^"\\]*(?:\\.[^"\\]*)*)"/g) || [];
  return matches.map((item) => item.slice(1, -1));
}

function parseAnnotationPaths(annotation: string) {
  const paramsMatch = annotation.match(/@\w+Mapping\s*\(([\s\S]*)\)\s*$/);
  if (!paramsMatch?.[1]) {
    return [''];
  }

  const params = paramsMatch[1];
  const namedMatch = params.match(/\b(?:value|path)\s*=\s*(\{[\s\S]*?\}|"(?:[^"\\]|\\.)*")/);
  const directMatch = params.trim().startsWith('"') || params.trim().startsWith('{')
    ? params
    : '';

  const paths = parseJavaStringLiterals(namedMatch?.[1] || directMatch);
  return paths.length ? paths : [''];
}

function parseAnnotationMethods(annotation: string) {
  if (/@GetMapping\b/.test(annotation)) {
    return ['GET'];
  }
  if (/@PostMapping\b/.test(annotation)) {
    return ['POST'];
  }
  if (/@PutMapping\b/.test(annotation)) {
    return ['PUT'];
  }
  if (/@DeleteMapping\b/.test(annotation)) {
    return ['DELETE'];
  }
  if (/@PatchMapping\b/.test(annotation)) {
    return ['PATCH'];
  }

  const requestMethods = annotation.match(/RequestMethod\.(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)/g) || [];
  return dedupeStrings(requestMethods.map((item) => item.split('.').pop() || ''));
}

function buildSpringRouteInfo(basePaths: string[], annotation: string): FunctionRouteInfo {
  const methodPaths = parseAnnotationPaths(annotation);
  const paths = dedupeStrings(
    (basePaths.length ? basePaths : ['']).flatMap((basePath) =>
      (methodPaths.length ? methodPaths : ['']).map((methodPath) => joinRoutePath(basePath, methodPath)),
    ),
  );

  return {
    path: paths.join(' | '),
    methods: parseAnnotationMethods(annotation),
    source: 'spring-web',
  };
}

function extractMethodName(header: string) {
  const compactHeader = header.replace(/\s+/g, ' ').trim();
  const methodMatch = compactHeader.match(/([A-Za-z_][A-Za-z0-9_]*)\s*\([^{};]*\)\s*(?:throws\b[^{};]*)?\{/);
  const methodName = methodMatch?.[1] || '';

  if (!methodName || JAVA_CONTROL_KEYWORDS.has(methodName)) {
    return '';
  }

  return methodName;
}

function extractSpringControllerEndpoints(filePath: string, content: string): SpringControllerEndpoint[] {
  const lines = content.split(/\r?\n/);
  const endpoints: SpringControllerEndpoint[] = [];
  const pendingAnnotations: string[] = [];
  let className = '';
  let controllerBasePaths = [''];
  let isControllerClass = false;
  let braceDepth = 0;
  let classBraceDepth = -1;

  for (let index = 0; index < lines.length; index += 1) {
    const trimmed = lines[index].trim();

    if (!trimmed || trimmed.startsWith('//') || trimmed.startsWith('/*') || trimmed.startsWith('*')) {
      braceDepth += countBraceDelta(lines[index] || '');
      continue;
    }

    if (!className && trimmed.startsWith('@')) {
      const annotation = consumeAnnotation(lines, index);
      pendingAnnotations.push(annotation.text);
      braceDepth += countBraceDeltaInRange(lines, index, annotation.endIndex);
      index = annotation.endIndex;
      continue;
    }

    if (!className) {
      const declaration = consumeDeclarationHeader(lines, index);
      const header = declaration.header;
      const classMatch = header.match(/\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b/);
      if (classMatch) {
        className = classMatch[1];
        isControllerClass = pendingAnnotations.some((annotation) => SPRING_CONTROLLER_ANNOTATION_REGEX.test(annotation));
        controllerBasePaths = isControllerClass
          ? dedupeStrings(
              pendingAnnotations
                .filter((annotation) => /@RequestMapping\b/.test(annotation))
                .flatMap((annotation) => parseAnnotationPaths(annotation)),
            )
          : [''];
        if (!controllerBasePaths.length) {
          controllerBasePaths = [''];
        }
        classBraceDepth = braceDepth + countBraceDeltaInRange(lines, index, declaration.endIndex);
      }

      pendingAnnotations.length = 0;
      braceDepth += countBraceDeltaInRange(lines, index, declaration.endIndex);
      index = declaration.endIndex;
      continue;
    }

    if (braceDepth !== classBraceDepth) {
      pendingAnnotations.length = 0;
      braceDepth += countBraceDelta(lines[index] || '');
      continue;
    }

    if (trimmed.startsWith('@')) {
      const annotation = consumeAnnotation(lines, index);
      pendingAnnotations.push(annotation.text);
      braceDepth += countBraceDeltaInRange(lines, index, annotation.endIndex);
      index = annotation.endIndex;
      continue;
    }

    const declaration = consumeDeclarationHeader(lines, index);
    const header = declaration.header;

    if (!isControllerClass) {
      pendingAnnotations.length = 0;
      braceDepth += countBraceDeltaInRange(lines, index, declaration.endIndex);
      index = declaration.endIndex;
      continue;
    }

    const mappingAnnotation = pendingAnnotations.find((annotation) => SPRING_MAPPING_ANNOTATION_REGEX.test(annotation));
    if (!mappingAnnotation) {
      pendingAnnotations.length = 0;
      braceDepth += countBraceDeltaInRange(lines, index, declaration.endIndex);
      index = declaration.endIndex;
      continue;
    }

    const methodName = extractMethodName(header);
    if (methodName) {
      endpoints.push({
        controllerName: className,
        methodName,
        filePath,
        route: buildSpringRouteInfo(controllerBasePaths, mappingAnnotation),
      });
    }

    pendingAnnotations.length = 0;
    braceDepth += countBraceDeltaInRange(lines, index, declaration.endIndex);
    index = declaration.endIndex;
  }

  return endpoints;
}

function buildSpringControllerSubFunction(endpoint: SpringControllerEndpoint): SubFunction {
  const bridge: FunctionBridgeInfo = {
    adapterId: SPRING_BOOT_ADAPTER_ID,
    framework: SPRING_BOOT_FRAMEWORK,
    kind: 'controller',
    reason: 'Spring Boot 通过框架路由将请求分发到 Controller 方法。',
  };

  return {
    name: `${endpoint.controllerName}.${endpoint.methodName}`,
    filePath: endpoint.filePath,
    summary: `Spring Controller 接口，负责处理 ${endpoint.route.path}`,
    drillDown: 1,
    route: endpoint.route,
    bridge,
  };
}

const springBootBridgeAdapter: FrameworkBridgeAdapter = {
  id: SPRING_BOOT_ADAPTER_ID,
  framework: SPRING_BOOT_FRAMEWORK,
  getEntryPointHints(context) {
    if (!isLikelySpringBootProject(context)) {
      return null;
    }

    const entryPoints = pickSpringEntryPointCandidates(context);
    if (!entryPoints.length) {
      return null;
    }

    return {
      adapterId: SPRING_BOOT_ADAPTER_ID,
      framework: SPRING_BOOT_FRAMEWORK,
      entryPoints,
      reason: '根据 Spring Boot 项目布局补充主启动类候选。',
    };
  },
  async buildEntryBridge(context) {
    if (!isLikelySpringBootProject(context) || !isLikelySpringBootEntryFile(context.entryFilePath, context.entryFileContent)) {
      return null;
    }

    const controllerCandidates = pickSpringControllerCandidates(context);
    if (!controllerCandidates.length) {
      return null;
    }

    const controllerFiles = await loadFileBatch(controllerCandidates, context.getFileContent);
    const endpoints = controllerFiles
      .flatMap((entry) => extractSpringControllerEndpoints(entry.path, entry.content))
      .sort((left, right) => {
        if (left.filePath !== right.filePath) {
          return left.filePath.localeCompare(right.filePath);
        }
        return left.methodName.localeCompare(right.methodName);
      });

    if (!endpoints.length) {
      return null;
    }

    return {
      adapterId: SPRING_BOOT_ADAPTER_ID,
      framework: SPRING_BOOT_FRAMEWORK,
      reason: '检测到 Spring Boot 启动类，使用 Controller 端点作为桥接起点。',
      rootSummary: '项目启动后由 Spring Boot 路由分发到 Controller，调用链从 Controller 端点开始展开。',
      nodes: endpoints.map(buildSpringControllerSubFunction),
    };
  },
};

const flaskBridgeAdapter: FrameworkBridgeAdapter = {
  id: PYTHON_FLASK_ADAPTER_ID,
  framework: PYTHON_FLASK_FRAMEWORK,
  getEntryPointHints(context) {
    if (!isLikelyPythonProject(context)) {
      return null;
    }

    const entryPoints = pickPythonEntryPointCandidates(context, (path) =>
      /(?:^|\/)(?:app|main|run|server|application|wsgi)\.py$/i.test(path),
    );
    if (!entryPoints.length) {
      return null;
    }

    return {
      adapterId: PYTHON_FLASK_ADAPTER_ID,
      framework: PYTHON_FLASK_FRAMEWORK,
      entryPoints,
      reason: '根据 Python Web/Wsgi 常见入口文件补充 Flask 候选。',
    };
  },
  async buildEntryBridge(context) {
    if (!isLikelyPythonProject(context) || !isLikelyPythonWebEntryFile(context.entryFilePath, context.entryFileContent)) {
      return null;
    }

    const endpoints = await collectFlaskEndpoints(context);
    if (!endpoints.length) {
      return null;
    }

    const wsgiMode = isPythonWsgiEntryFile(context.entryFilePath, context.entryFileContent);
    return {
      adapterId: PYTHON_FLASK_ADAPTER_ID,
      framework: PYTHON_FLASK_FRAMEWORK,
      reason: wsgiMode
        ? '检测到 Python WSGI 启动文件，使用 Flask 路由处理函数作为桥接起点。'
        : '检测到 Flask Web 入口，使用 Flask 路由处理函数作为桥接起点。',
      rootSummary: wsgiMode
        ? '项目通过 WSGI 暴露 Flask 应用，请求经 Flask 路由分发到响应函数，调用链从路由处理函数开始展开。'
        : '项目通过 Flask 路由分发请求，调用链从路由处理函数开始展开。',
      nodes: endpoints.map((endpoint) =>
        buildRouteHandlerSubFunction(
          endpoint,
          PYTHON_FLASK_ADAPTER_ID,
          PYTHON_FLASK_FRAMEWORK,
          'Flask 通过装饰器路由把 HTTP 请求分发到响应函数。',
        )),
    };
  },
};

const fastApiBridgeAdapter: FrameworkBridgeAdapter = {
  id: PYTHON_FASTAPI_ADAPTER_ID,
  framework: PYTHON_FASTAPI_FRAMEWORK,
  getEntryPointHints(context) {
    if (!isLikelyPythonProject(context)) {
      return null;
    }

    const entryPoints = pickPythonEntryPointCandidates(context, (path) =>
      /(?:^|\/)(?:app|main|server|application|asgi)\.py$/i.test(path),
    );
    if (!entryPoints.length) {
      return null;
    }

    return {
      adapterId: PYTHON_FASTAPI_ADAPTER_ID,
      framework: PYTHON_FASTAPI_FRAMEWORK,
      entryPoints,
      reason: '根据 Python Web/Asgi 常见入口文件补充 FastAPI 候选。',
    };
  },
  async buildEntryBridge(context) {
    if (!isLikelyPythonProject(context) || !isLikelyPythonWebEntryFile(context.entryFilePath, context.entryFileContent)) {
      return null;
    }

    const endpoints = await collectFastApiEndpoints(context);
    if (!endpoints.length) {
      return null;
    }

    return {
      adapterId: PYTHON_FASTAPI_ADAPTER_ID,
      framework: PYTHON_FASTAPI_FRAMEWORK,
      reason: '检测到 FastAPI Web 入口，使用 FastAPI 路由处理函数作为桥接起点。',
      rootSummary: '项目通过 FastAPI 路由分发请求，调用链从路由处理函数开始展开。',
      nodes: endpoints.map((endpoint) =>
        buildRouteHandlerSubFunction(
          endpoint,
          PYTHON_FASTAPI_ADAPTER_ID,
          PYTHON_FASTAPI_FRAMEWORK,
          'FastAPI 通过装饰器路由把 HTTP 请求分发到响应函数。',
        )),
    };
  },
};

const djangoBridgeAdapter: FrameworkBridgeAdapter = {
  id: PYTHON_DJANGO_ADAPTER_ID,
  framework: PYTHON_DJANGO_FRAMEWORK,
  getEntryPointHints(context) {
    if (!isLikelyPythonProject(context)) {
      return null;
    }

    const entryPoints = pickPythonEntryPointCandidates(context, (path) =>
      /(?:^|\/)(?:manage|wsgi|asgi)\.py$/i.test(path),
    );
    if (!entryPoints.length) {
      return null;
    }

    return {
      adapterId: PYTHON_DJANGO_ADAPTER_ID,
      framework: PYTHON_DJANGO_FRAMEWORK,
      entryPoints,
      reason: '根据 Django 常见入口与 WSGI/ASGI 启动文件补充候选。',
    };
  },
  async buildEntryBridge(context) {
    if (!isLikelyPythonProject(context) || !isLikelyPythonWebEntryFile(context.entryFilePath, context.entryFileContent)) {
      return null;
    }

    const djangoEntry =
      /(?:^|\/)manage\.py$/i.test(context.entryFilePath) ||
      hasDjangoMarkers(context.entryFileContent) ||
      context.codeFilePaths.some((path) => DJANGO_URLS_PATH_REGEX.test(path));
    if (!djangoEntry) {
      return null;
    }

    const endpoints = await collectDjangoEndpoints(context);
    if (!endpoints.length) {
      return null;
    }

    const wsgiMode = isPythonWsgiEntryFile(context.entryFilePath, context.entryFileContent);
    return {
      adapterId: PYTHON_DJANGO_ADAPTER_ID,
      framework: PYTHON_DJANGO_FRAMEWORK,
      reason: wsgiMode
        ? '检测到 Django WSGI 启动文件，使用 URLConf 解析结果作为桥接起点。'
        : '检测到 Django 入口文件，使用 URLConf 解析结果作为桥接起点。',
      rootSummary: wsgiMode
        ? '项目通过 Django WSGI/URLConf 将请求分发到视图函数，调用链从路由响应函数开始展开。'
        : '项目通过 Django URLConf 将请求分发到视图函数，调用链从路由响应函数开始展开。',
      nodes: endpoints.map((endpoint) =>
        buildRouteHandlerSubFunction(
          endpoint,
          PYTHON_DJANGO_ADAPTER_ID,
          PYTHON_DJANGO_FRAMEWORK,
          'Django 通过 URLConf 将 HTTP 请求分发到视图函数或视图类。',
        )),
    };
  },
};

const FRAMEWORK_BRIDGE_ADAPTERS: FrameworkBridgeAdapter[] = [
  springBootBridgeAdapter,
  djangoBridgeAdapter,
  fastApiBridgeAdapter,
  flaskBridgeAdapter,
];

export async function collectFrameworkEntryPointHints(context: FrameworkProjectContext) {
  const hints = await Promise.all(
    FRAMEWORK_BRIDGE_ADAPTERS.map((adapter) => adapter.getEntryPointHints?.(context) || null),
  );

  return hints.filter((hint): hint is FrameworkEntryPointHint => Boolean(hint));
}

export async function resolveFrameworkEntryBridge(context: FrameworkEntryBridgeContext) {
  for (const adapter of FRAMEWORK_BRIDGE_ADAPTERS) {
    const bridge = await adapter.buildEntryBridge(context);
    if (bridge) {
      return bridge;
    }
  }

  return null;
}
