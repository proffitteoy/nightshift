type BlockKind = 'brace' | 'indent' | 'end' | 'line';
type LocateStrategy = 'same_file' | 'ai_guess' | 'repo_search';

interface FunctionDefinitionMatch {
  index: number;
  matchedSignature: string;
  kind: BlockKind;
}

interface FunctionReferenceParts {
  cleaned: string;
  bareName: string;
  ownerName: string;
  ownerChain: string[];
}

export interface LocatedFunction {
  functionName: string;
  normalizedName: string;
  filePath: string;
  snippet: string;
  startLine: number;
  endLine: number;
  matchedSignature: string;
  strategy: LocateStrategy;
}

const MAX_SNIPPET_LINES = 240;
const FALLBACK_WINDOW_LINES = 80;
const IDENTIFIER_IGNORE = new Set([
  'async',
  'function',
  'def',
  'func',
  'fn',
  'public',
  'private',
  'protected',
  'static',
  'export',
  'default',
  'return',
  'const',
  'let',
  'var',
  'class',
  'struct',
  'interface',
]);

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function clipLines(text: string, maxLines: number): string {
  const lines = text.split('\n');
  if (lines.length <= maxLines) {
    return text;
  }

  return lines.slice(0, maxLines).join('\n');
}

function getLineNumberFromIndex(content: string, index: number): number {
  return content.slice(0, index).split('\n').length;
}

function getLineStartIndex(content: string, index: number): number {
  const previousBreak = content.lastIndexOf('\n', index);
  return previousBreak === -1 ? 0 : previousBreak + 1;
}

function sanitizeFunctionReference(rawName: string) {
  return rawName
    .trim()
    .replace(/[`"'“”‘’]/g, '')
    .replace(/[`"'“”‘’]/g, '')
    .replace(/[`"'“”‘’]/g, '');
}

function normalizeIdentifier(value: string): string {
  const identifiers = value.match(/[A-Za-z_$][A-Za-z0-9_$]*/g) || [];
  for (let index = identifiers.length - 1; index >= 0; index -= 1) {
    const candidate = identifiers[index];
    if (!IDENTIFIER_IGNORE.has(candidate)) {
      return candidate;
    }
  }
  return '';
}

function extractReferenceParts(rawName: string): FunctionReferenceParts {
  const cleaned = sanitizeFunctionReference(rawName);
  const segments = cleaned.split(/::|->|\?\.|\.|#|\.\:/).map((segment) => segment.trim()).filter(Boolean);
  const bareName = normalizeIdentifier(segments[segments.length - 1] || cleaned);
  const ownerChain = segments
    .slice(0, -1)
    .map((segment) => normalizeIdentifier(segment))
    .filter(Boolean);

  return {
    cleaned,
    bareName,
    ownerName: ownerChain[ownerChain.length - 1] || '',
    ownerChain,
  };
}

function buildDefinitionPatterns(functionName: string): Array<{
  regex: RegExp;
  kind: BlockKind;
}> {
  const name = escapeRegex(functionName);

  return [
    {
      regex: new RegExp(
        `^\\s*(?:export\\s+)?(?:default\\s+)?(?:async\\s+)?function\\s+${name}\\s*\\(`,
        'm',
      ),
      kind: 'brace',
    },
    {
      regex: new RegExp(
        `^\\s*(?:export\\s+)?(?:const|let|var)\\s+${name}\\b[\\s\\S]{0,200}?=>`,
        'm',
      ),
      kind: 'brace',
    },
    {
      regex: new RegExp(
        `^\\s*(?:export\\s+)?(?:const|let|var)\\s+${name}\\b[\\s\\S]{0,200}?function\\b`,
        'm',
      ),
      kind: 'brace',
    },
    {
      regex: new RegExp(
        `^\\s*${name}\\s*:\\s*(?:async\\s*)?(?:function\\b|\\([^\\n]*?=>)`,
        'm',
      ),
      kind: 'brace',
    },
    {
      regex: new RegExp(
        `^\\s*(?:public|private|protected|internal|static|async|readonly|override|get|set|abstract|final|open|virtual|synchronized|inline|operator|suspend|external|mutating|nonmutating|class|required|convenience|fileprivate|default|unsafe|sealed|tailrec|infix\\s+)*${name}\\s*\\([^\\n]*\\)\\s*(?::\\s*[^\\{=\\n]+)?\\s*\\{`,
        'm',
      ),
      kind: 'brace',
    },
    {
      regex: new RegExp(`^\\s*(?:async\\s+)?def\\s+${name}\\s*\\(`, 'm'),
      kind: 'indent',
    },
    {
      regex: new RegExp(`^\\s*func\\s+(?:\\([^)]*\\)\\s*)?${name}\\s*\\(`, 'm'),
      kind: 'brace',
    },
    {
      regex: new RegExp(
        `^\\s*(?:pub(?:\\([^)]*\\))?\\s+)?(?:async\\s+)?fn\\s+${name}\\s*(?:<[^>]+>)?\\s*\\(`,
        'm',
      ),
      kind: 'brace',
    },
    {
      regex: new RegExp(
        `^\\s*(?:public|private|protected|internal|open|final|abstract|override|suspend|inline|operator|infix|external|tailrec|data|sealed|expect|actual\\s+)*fun\\s+${name}\\s*\\(`,
        'm',
      ),
      kind: 'brace',
    },
    {
      regex: new RegExp(
        `^\\s*(?:public|private|protected|fileprivate|internal|open|static|class|override|mutating|nonmutating|final|convenience|required\\s+)*func\\s+${name}\\s*\\(`,
        'm',
      ),
      kind: 'brace',
    },
    {
      regex: new RegExp(
        `^\\s*(?:public|private|protected|static|final|abstract\\s+)*function\\s+${name}\\s*\\(`,
        'm',
      ),
      kind: 'brace',
    },
    {
      regex: new RegExp(`^\\s*def\\s+${name}\\b`, 'm'),
      kind: 'end',
    },
    {
      regex: new RegExp(`^\\s*class\\s+${name}\\b[^\\n:]*:`, 'm'),
      kind: 'indent',
    },
    {
      regex: new RegExp(
        `^\\s*(?:export\\s+)?(?:default\\s+)?class\\s+${name}\\b[^\\{\\n]*\\{`,
        'm',
      ),
      kind: 'brace',
    },
    {
      regex: new RegExp(
        `^\\s*(?:template\\s*<[^>]+>\\s*)?(?:inline\\s+|static\\s+|virtual\\s+|constexpr\\s+|consteval\\s+|extern\\s+|friend\\s+|unsigned\\s+|signed\\s+|long\\s+|short\\s+|const\\s+|volatile\\s+|mutable\\s+|typename\\s+|auto\\s+|[A-Za-z_][\\w:<>,*&\\[\\]\\s]+)?\\b${name}\\s*\\(`,
        'm',
      ),
      kind: 'brace',
    },
  ];
}

function buildQualifiedDefinitionPatterns(ownerChain: string[], bareName: string): Array<{
  regex: RegExp;
  kind: BlockKind;
}> {
  if (!ownerChain.length || !bareName) {
    return [];
  }

  const ownerPattern = ownerChain.map((segment) => escapeRegex(segment)).join('\\s*::\\s*');
  const ownerDotPattern = ownerChain.map((segment) => escapeRegex(segment)).join('\\s*\\.\\s*');
  const name = escapeRegex(bareName);

  return [
    {
      regex: new RegExp(
        `^\\s*(?:template\\s*<[^>]+>\\s*)?(?:inline\\s+|static\\s+|virtual\\s+|constexpr\\s+|consteval\\s+|extern\\s+|friend\\s+|unsigned\\s+|signed\\s+|long\\s+|short\\s+|const\\s+|volatile\\s+|mutable\\s+|typename\\s+|auto\\s+|[A-Za-z_][\\w:<>,*&\\[\\]\\s]+)?\\b${ownerPattern}\\s*::\\s*${name}\\s*\\(`,
        'm',
      ),
      kind: 'brace',
    },
    {
      regex: new RegExp(
        `^\\s*${ownerDotPattern}\\s*\\.\\s*(?:prototype\\s*\\.\\s*)?${name}\\s*=\\s*(?:async\\s*)?(?:function\\b|\\([^\\n]*?=>)`,
        'm',
      ),
      kind: 'brace',
    },
    {
      regex: new RegExp(
        `^\\s*${ownerDotPattern}\\s*\\.\\s*${name}\\s*:\\s*(?:async\\s*)?(?:function\\b|\\([^\\n]*?=>)`,
        'm',
      ),
      kind: 'brace',
    },
  ];
}

function findRegexMatch(
  content: string,
  patterns: Array<{ regex: RegExp; kind: BlockKind }>,
  offset = 0,
): FunctionDefinitionMatch | null {
  let bestMatch: FunctionDefinitionMatch | null = null;

  for (const pattern of patterns) {
    const match = pattern.regex.exec(content);
    if (!match) {
      continue;
    }

    const nextMatch: FunctionDefinitionMatch = {
      index: offset + match.index,
      matchedSignature: match[0].trim(),
      kind: pattern.kind,
    };

    if (!bestMatch || nextMatch.index < bestMatch.index) {
      bestMatch = nextMatch;
    }
  }

  return bestMatch;
}

function findMatchingBrace(content: string, braceIndex: number): number {
  let depth = 0;
  for (let index = braceIndex; index < content.length; index += 1) {
    const char = content[index];
    if (char === '{') {
      depth += 1;
    } else if (char === '}') {
      depth -= 1;
      if (depth === 0) {
        return index;
      }
    }
  }
  return -1;
}

function findClassScopedDefinitionMatch(
  content: string,
  ownerName: string,
  bareName: string,
): FunctionDefinitionMatch | null {
  if (!ownerName || !bareName) {
    return null;
  }

  const owner = escapeRegex(ownerName);
  const blockPatterns = [
    new RegExp(`\\b(?:class|struct|interface|trait)\\s+${owner}\\b[^\\{\\n]*\\{`, 'g'),
    new RegExp(`\\bimpl(?:\\s*<[^>]+>)?\\s+${owner}\\b[^\\{\\n]*\\{`, 'g'),
  ];

  let bestMatch: FunctionDefinitionMatch | null = null;
  for (const blockPattern of blockPatterns) {
    const blocks = content.matchAll(blockPattern);
    for (const block of blocks) {
      const matchIndex = block.index ?? -1;
      if (matchIndex === -1) {
        continue;
      }

      const bodyStart = content.indexOf('{', matchIndex);
      if (bodyStart === -1) {
        continue;
      }

      const bodyEnd = findMatchingBrace(content, bodyStart);
      if (bodyEnd === -1) {
        continue;
      }

      const blockContent = content.slice(matchIndex, bodyEnd + 1);
      const innerMatch = findRegexMatch(blockContent, buildDefinitionPatterns(bareName), matchIndex);
      if (!innerMatch) {
        continue;
      }

      if (!bestMatch || innerMatch.index < bestMatch.index) {
        bestMatch = innerMatch;
      }
    }
  }

  return bestMatch;
}

function findPythonClassScopedDefinitionMatch(
  content: string,
  ownerName: string,
  bareName: string,
): FunctionDefinitionMatch | null {
  if (!ownerName || !bareName) {
    return null;
  }

  const owner = escapeRegex(ownerName);
  const classPattern = new RegExp(`^\\s*class\\s+${owner}\\b[^\\n:]*:`, 'gm');
  const lines = content.split('\n');
  let bestMatch: FunctionDefinitionMatch | null = null;
  let classMatch: RegExpExecArray | null;

  while ((classMatch = classPattern.exec(content)) !== null) {
    const classIndex = classMatch.index;
    const startLine = getLineNumberFromIndex(content, classIndex);
    const startLineIndex = startLine - 1;
    const lineStartIndex = getLineStartIndex(content, classIndex);
    const classBlock = extractIndentedBlock(lines, startLineIndex);
    const blockContent = lines.slice(startLineIndex, classBlock.endLineIndex + 1).join('\n');
    const innerMatch = findRegexMatch(blockContent, buildDefinitionPatterns(bareName), lineStartIndex);

    if (!innerMatch) {
      continue;
    }

    if (!bestMatch || innerMatch.index < bestMatch.index) {
      bestMatch = innerMatch;
    }
  }

  return bestMatch;
}

function findDefinitionMatch(content: string, rawFunctionName: string): FunctionDefinitionMatch | null {
  const reference = extractReferenceParts(rawFunctionName);
  if (!reference.bareName) {
    return null;
  }

  const qualifiedMatch = findRegexMatch(
    content,
    buildQualifiedDefinitionPatterns(reference.ownerChain, reference.bareName),
  );
  if (qualifiedMatch) {
    return qualifiedMatch;
  }

  const classScopedMatch = findClassScopedDefinitionMatch(
    content,
    reference.ownerName,
    reference.bareName,
  );
  if (classScopedMatch) {
    return classScopedMatch;
  }

  const pythonClassScopedMatch = findPythonClassScopedDefinitionMatch(
    content,
    reference.ownerName,
    reference.bareName,
  );
  if (pythonClassScopedMatch) {
    return pythonClassScopedMatch;
  }

  return findRegexMatch(content, buildDefinitionPatterns(reference.bareName));
}

function extractByLineWindow(
  lines: string[],
  startLineIndex: number,
): { snippet: string; endLineIndex: number } {
  const endLineIndex = Math.min(lines.length - 1, startLineIndex + FALLBACK_WINDOW_LINES - 1);
  return {
    snippet: lines.slice(startLineIndex, endLineIndex + 1).join('\n'),
    endLineIndex,
  };
}

function extractBraceBlock(
  content: string,
  lineStartIndex: number,
  matchIndex: number,
  lines: string[],
  startLineIndex: number,
): { snippet: string; endLineIndex: number } {
  const bodyStart = content.indexOf('{', matchIndex);

  if (bodyStart === -1) {
    return extractByLineWindow(lines, startLineIndex);
  }

  const endIndex = findMatchingBrace(content, bodyStart);
  if (endIndex === -1) {
    return extractByLineWindow(lines, startLineIndex);
  }

  const snippet = content.slice(lineStartIndex, endIndex + 1);
  return {
    snippet,
    endLineIndex: getLineNumberFromIndex(content, endIndex) - 1,
  };
}

function getIndent(line: string): number {
  const expanded = line.replace(/\t/g, '    ');
  return expanded.length - expanded.trimStart().length;
}

function extractIndentedBlock(
  lines: string[],
  startLineIndex: number,
): { snippet: string; endLineIndex: number } {
  const startLine = lines[startLineIndex] || '';
  const baseIndent = getIndent(startLine);
  let endLineIndex = lines.length - 1;

  for (let index = startLineIndex + 1; index < lines.length; index += 1) {
    const line = lines[index];
    if (!line.trim()) {
      continue;
    }

    if (getIndent(line) <= baseIndent) {
      endLineIndex = index - 1;
      break;
    }
  }

  return {
    snippet: lines.slice(startLineIndex, endLineIndex + 1).join('\n'),
    endLineIndex,
  };
}

function extractEndDelimitedBlock(
  lines: string[],
  startLineIndex: number,
): { snippet: string; endLineIndex: number } {
  let depth = 0;
  let endLineIndex = startLineIndex;

  for (let index = startLineIndex; index < lines.length; index += 1) {
    const trimmed = lines[index].trim();

    if (/^(def|class|module|if|unless|case|begin|do)\b/.test(trimmed)) {
      depth += 1;
    }

    if (/^end\b/.test(trimmed)) {
      depth -= 1;
      if (depth <= 0) {
        endLineIndex = index;
        break;
      }
    }
  }

  if (endLineIndex === startLineIndex) {
    return extractByLineWindow(lines, startLineIndex);
  }

  return {
    snippet: lines.slice(startLineIndex, endLineIndex + 1).join('\n'),
    endLineIndex,
  };
}

function extractLineBasedBlock(
  lines: string[],
  startLineIndex: number,
): { snippet: string; endLineIndex: number } {
  let endLineIndex = Math.min(lines.length - 1, startLineIndex + 8);

  for (let index = startLineIndex + 1; index <= endLineIndex; index += 1) {
    const trimmed = (lines[index] || '').trim();
    if (!trimmed) {
      endLineIndex = index - 1;
      break;
    }
  }

  return {
    snippet: lines.slice(startLineIndex, endLineIndex + 1).join('\n'),
    endLineIndex,
  };
}

export function normalizeFunctionName(rawName: string): string {
  return extractReferenceParts(rawName).bareName;
}

export function locateFunctionInContent(
  content: string,
  filePath: string,
  rawFunctionName: string,
  strategy: LocateStrategy,
): LocatedFunction | null {
  const normalizedName = normalizeFunctionName(rawFunctionName);
  if (!normalizedName) {
    return null;
  }

  const match = findDefinitionMatch(content, rawFunctionName);
  if (!match) {
    return null;
  }

  const lines = content.split('\n');
  const startLine = getLineNumberFromIndex(content, match.index);
  const startLineIndex = startLine - 1;
  const lineStartIndex = getLineStartIndex(content, match.index);

  let extracted: { snippet: string; endLineIndex: number };
  switch (match.kind) {
    case 'indent':
      extracted = extractIndentedBlock(lines, startLineIndex);
      break;
    case 'end':
      extracted = extractEndDelimitedBlock(lines, startLineIndex);
      break;
    case 'line':
      extracted = extractLineBasedBlock(lines, startLineIndex);
      break;
    case 'brace':
    default:
      extracted = extractBraceBlock(content, lineStartIndex, match.index, lines, startLineIndex);
      break;
  }

  const snippet = clipLines(extracted.snippet.trim(), MAX_SNIPPET_LINES);

  return {
    functionName: rawFunctionName,
    normalizedName,
    filePath,
    snippet,
    startLine,
    endLine: extracted.endLineIndex + 1,
    matchedSignature: match.matchedSignature,
    strategy,
  };
}

function getDirectory(path: string): string {
  const lastSlash = path.lastIndexOf('/');
  return lastSlash === -1 ? '' : path.slice(0, lastSlash);
}

function getBaseName(path: string): string {
  const lastSlash = path.lastIndexOf('/');
  return lastSlash === -1 ? path : path.slice(lastSlash + 1);
}

function countSharedSegments(pathA: string, pathB: string): number {
  const segmentsA = pathA.split('/').filter(Boolean);
  const segmentsB = pathB.split('/').filter(Boolean);
  const count = Math.min(segmentsA.length, segmentsB.length);
  let shared = 0;

  for (let index = 0; index < count; index += 1) {
    if (segmentsA[index] !== segmentsB[index]) {
      break;
    }
    shared += 1;
  }

  return shared;
}

function scoreFile(path: string, parentDirectory: string, reference: FunctionReferenceParts): number {
  const baseName = getBaseName(path).toLowerCase();
  const pathLower = path.toLowerCase();
  let score = 0;

  if (getDirectory(path) === parentDirectory) {
    score += 200;
  }

  score += countSharedSegments(parentDirectory, getDirectory(path)) * 10;

  if (reference.bareName && baseName.includes(reference.bareName.toLowerCase())) {
    score += 120;
  }

  if (reference.bareName && pathLower.includes(reference.bareName.toLowerCase())) {
    score += 40;
  }

  if (reference.ownerName && pathLower.includes(reference.ownerName.toLowerCase())) {
    score += 60;
  }

  return score;
}

export function rankFilesForRepositorySearch(
  filePaths: string[],
  parentFilePath: string,
  rawFunctionName: string,
): string[] {
  const reference = extractReferenceParts(rawFunctionName);
  const parentDirectory = getDirectory(parentFilePath);

  return [...new Set(filePaths)].sort((left, right) => {
    const leftScore = scoreFile(left, parentDirectory, reference);
    const rightScore = scoreFile(right, parentDirectory, reference);

    if (leftScore !== rightScore) {
      return rightScore - leftScore;
    }

    return left.localeCompare(right);
  });
}
