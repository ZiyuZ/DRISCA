import { cp, mkdir, rm, copyFile } from 'node:fs/promises';
import { resolve, basename } from 'node:path';

const root = process.env.DRISCA_REPOSITORY;
if (!root) throw new Error('请设置 DRISCA_REPOSITORY');
const content = resolve(root, '.github/docs-site/content');
await rm(content, { recursive: true, force: true });
await mkdir(content, { recursive: true });
await cp(resolve(root, 'docs'), content, {
  recursive: true,
  filter: (path) => !['.git', '.rumdl_cache'].includes(basename(path)),
});
const publicAssets = resolve(content, 'public/assets');
await mkdir(publicAssets, { recursive: true });
await copyFile(resolve(root, 'docs/assets/icon.png'), resolve(publicAssets, 'icon.png'));
