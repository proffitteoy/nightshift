import React from 'react';
import { ChevronRight, ChevronDown, File, Folder } from 'lucide-react';
import { FileNode } from '../types/project';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface FileTreeProps {
  nodes: FileNode[];
  onFileSelect: (path: string) => void;
  selectedPath?: string;
}

const TreeNode: React.FC<{
  node: FileNode;
  depth: number;
  onFileSelect: (path: string) => void;
  selectedPath?: string;
}> = ({ node, depth, onFileSelect, selectedPath }) => {
  const [isOpen, setIsOpen] = React.useState(false);
  const isSelected = selectedPath === node.path;

  const handleClick = () => {
    if (node.type === 'folder') {
      setIsOpen(!isOpen);
    } else {
      onFileSelect(node.path);
    }
  };

  return (
    <div>
      <div
        className={cn(
          "flex items-center py-1 px-2 cursor-pointer hover:bg-zinc-100 transition-colors rounded-md text-sm",
          isSelected && "bg-emerald-50 text-emerald-700 font-medium",
          !isSelected && "text-zinc-600"
        )}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={handleClick}
      >
        <span className="mr-1.5 opacity-40">
          {node.type === 'folder' ? (
            isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />
          ) : (
            <div className="w-3.5" />
          )}
        </span>
        <span className="mr-2">
          {node.type === 'folder' ? (
            <Folder size={16} className="text-amber-500/70" />
          ) : (
            <File size={16} className="text-zinc-400" />
          )}
        </span>
        <span className="truncate">{node.name}</span>
      </div>
      {node.type === 'folder' && isOpen && node.children && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              onFileSelect={onFileSelect}
              selectedPath={selectedPath}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export const FileTree: React.FC<FileTreeProps> = ({ nodes, onFileSelect, selectedPath }) => {
  return (
    <div className="py-2">
      {nodes.map((node) => (
        <TreeNode
          key={node.path}
          node={node}
          depth={0}
          onFileSelect={onFileSelect}
          selectedPath={selectedPath}
        />
      ))}
    </div>
  );
};
