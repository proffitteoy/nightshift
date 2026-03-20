import { fetchFileContent, fetchRepoTree, parseGithubUrl } from './github';
import type { FileNode, ProjectDataSourceDescriptor, ProjectFile } from '../types/project';

export type ProjectFileMatcher<T> = (
  content: string,
  path: string,
) => Promise<T | null> | T | null;

export interface ProjectSearchMatch<T> {
  path: string;
  result: T;
}

export interface ProjectDataSource {
  descriptor: ProjectDataSourceDescriptor;
  listFiles: () => Promise<ProjectFile[]>;
  readFile: (path: string) => Promise<string>;
  searchFiles: <T>(
    paths: string[],
    matcher: ProjectFileMatcher<T>,
  ) => Promise<ProjectSearchMatch<T> | null>;
}

function createCachedFileReader(loader: (path: string) => Promise<string>) {
  const cache = new Map<string, Promise<string>>();

  return (path: string) => {
    const cached = cache.get(path);
    if (cached) {
      return cached;
    }

    const request = loader(path).catch((error) => {
      cache.delete(path);
      throw error;
    });
    cache.set(path, request);
    return request;
  };
}

function createSearchFiles(readFile: (path: string) => Promise<string>) {
  return async function searchFiles<T>(
    paths: string[],
    matcher: ProjectFileMatcher<T>,
  ): Promise<ProjectSearchMatch<T> | null> {
    for (const path of paths) {
      const content = await readFile(path);
      const result = await matcher(content, path);
      if (result) {
        return { path, result };
      }
    }

    return null;
  };
}

function buildProjectFilesFromPaths(
  items: Array<{ path: string; size?: number }>,
): ProjectFile[] {
  const entryMap = new Map<string, ProjectFile>();

  for (const item of items) {
    const normalizedPath = item.path.replace(/^\/+|\/+$/g, '');
    if (!normalizedPath) {
      continue;
    }

    const segments = normalizedPath.split('/').filter(Boolean);
    let currentPath = '';

    for (let index = 0; index < segments.length; index += 1) {
      currentPath = currentPath ? `${currentPath}/${segments[index]}` : segments[index];
      const isFile = index === segments.length - 1;

      if (!entryMap.has(currentPath)) {
        entryMap.set(currentPath, {
          path: currentPath,
          mode: isFile ? '100644' : '040000',
          type: isFile ? 'blob' : 'tree',
          sha: currentPath,
          size: isFile ? item.size : undefined,
          url: '',
        });
      }
    }
  }

  return [...entryMap.values()].sort((left, right) => left.path.localeCompare(right.path));
}

function getLocalRootName(files: File[]) {
  const firstPath = files[0]?.webkitRelativePath || files[0]?.name || 'local-project';
  const [rootName] = firstPath.split('/').filter(Boolean);
  return rootName || 'local-project';
}

function normalizeLocalFilePath(file: File) {
  const relativePath = file.webkitRelativePath || file.name;
  const segments = relativePath.split('/').filter(Boolean);
  if (segments.length <= 1) {
    return file.name;
  }
  return segments.slice(1).join('/');
}

export function createGithubProjectDataSource(url: string): ProjectDataSource | null {
  const parsed = parseGithubUrl(url.trim());
  if (!parsed) {
    return null;
  }

  const location = `https://github.com/${parsed.owner}/${parsed.repo}`;
  let filesPromise: Promise<ProjectFile[]> | null = null;
  const readFile = createCachedFileReader((path) => fetchFileContent(parsed.owner, parsed.repo, path));

  return {
    descriptor: {
      type: 'github',
      key: `github:${parsed.owner}/${parsed.repo}`,
      projectName: parsed.repo,
      fullName: `${parsed.owner}/${parsed.repo}`,
      location,
      owner: parsed.owner,
      repo: parsed.repo,
    },
    listFiles: async () => {
      if (!filesPromise) {
        filesPromise = fetchRepoTree(parsed.owner, parsed.repo).then((response) => response.tree);
      }
      return filesPromise;
    },
    readFile,
    searchFiles: createSearchFiles(readFile),
  };
}

export function createLocalProjectDataSource(
  files: File[],
  options: { sessionKey?: string } = {},
): ProjectDataSource {
  const validFiles = files
    .map((file) => ({
      file,
      path: normalizeLocalFilePath(file),
    }))
    .filter((entry) => Boolean(entry.path));

  if (validFiles.length === 0) {
    throw new Error('未能从所选目录读取到可分析文件');
  }

  const rootName = getLocalRootName(files);
  const fileMap = new Map(validFiles.map((entry) => [entry.path, entry.file]));
  const projectFiles = buildProjectFilesFromPaths(
    validFiles.map((entry) => ({
      path: entry.path,
      size: entry.file.size,
    })),
  );
  const readFile = createCachedFileReader(async (path) => {
    const file = fileMap.get(path);
    if (!file) {
      throw new Error(`未找到本地文件: ${path}`);
    }
    return file.text();
  });

  return {
    descriptor: {
      type: 'local',
      key: options.sessionKey || `local:${rootName}`,
      projectName: rootName,
      fullName: rootName,
      location: `local://${encodeURIComponent(rootName)}`,
    },
    listFiles: async () => projectFiles,
    readFile,
    searchFiles: createSearchFiles(readFile),
  };
}

export function buildFileTree(files: ProjectFile[]): FileNode[] {
  const root: FileNode[] = [];
  const map: Record<string, FileNode> = {};

  files.forEach((file) => {
    const parts = file.path.split('/');
    let currentPath = '';

    parts.forEach((part, index) => {
      const isLast = index === parts.length - 1;
      const parentPath = currentPath;
      currentPath = currentPath ? `${currentPath}/${part}` : part;

      if (!map[currentPath]) {
        const node: FileNode = {
          name: part,
          path: currentPath,
          type: isLast && file.type === 'blob' ? 'file' : 'folder',
          children: isLast && file.type === 'blob' ? undefined : [],
        };
        map[currentPath] = node;

        if (parentPath) {
          map[parentPath].children?.push(node);
        } else {
          root.push(node);
        }
      }
    });
  });

  const sortTree = (nodes: FileNode[]) => {
    nodes.sort((left, right) => {
      if (left.type === right.type) {
        return left.name.localeCompare(right.name);
      }
      return left.type === 'folder' ? -1 : 1;
    });

    nodes.forEach((node) => {
      if (node.children) {
        sortTree(node.children);
      }
    });
  };

  sortTree(root);
  return root;
}
