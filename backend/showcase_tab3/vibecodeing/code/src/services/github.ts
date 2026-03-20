import { GithubTreeResponse } from '../types/github';
import { getGithubToken } from './appSettings';

export const parseGithubUrl = (url: string) => {
  try {
    const regex = /github\.com\/([^/]+)\/([^/]+)/;
    const match = url.match(regex);
    if (match) {
      return { owner: match[1], repo: match[2].replace(/\.git$/, '') };
    }
    return null;
  } catch {
    return null;
  }
};

const createGithubHeaders = () => {
  const githubToken = getGithubToken();
  const headers: Record<string, string> = {
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  };

  if (githubToken) {
    headers.Authorization = `Bearer ${githubToken}`;
  }

  return headers;
};

export const fetchRepoTree = async (owner: string, repo: string, branch: string = 'main'): Promise<GithubTreeResponse> => {
  const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/git/trees/${branch}?recursive=1`, {
    headers: createGithubHeaders(),
  });
  
  if (!response.ok) {
    if (response.status === 404 && branch === 'main') {
      // Try 'master' if 'main' fails
      return fetchRepoTree(owner, repo, 'master');
    }
    
    if (response.status === 403) {
      const rateLimitReset = response.headers.get('X-RateLimit-Reset');
      if (rateLimitReset) {
        const resetDate = new Date(parseInt(rateLimitReset) * 1000);
        throw new Error(`GitHub API rate limit exceeded. Resets at ${resetDate.toLocaleTimeString()}.`);
      }
      throw new Error('GitHub API access forbidden. This might be a private repository or rate limit.');
    }

    if (response.status === 404) {
      throw new Error('Repository or branch not found. Please check if the URL is correct and the repository is public.');
    }

    throw new Error(`GitHub API Error: ${response.status} ${response.statusText}`);
  }
  return response.json();
};

export const fetchFileContent = async (owner: string, repo: string, path: string): Promise<string> => {
  const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/contents/${path}`, {
    headers: createGithubHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch file content');
  const data = await response.json();
  const encodedContent = typeof data.content === 'string' ? data.content.replace(/\n/g, '') : '';
  return atob(encodedContent);
};
