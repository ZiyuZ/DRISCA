import { defineConfig } from 'vitepress';
import { withMermaid } from 'vitepress-mermaid-viewer';
import { readdirSync, readFileSync } from 'node:fs';
import { resolve, basename } from 'node:path';

const root = process.env.DRISCA_REPOSITORY;
if (!root) throw new Error('请设置 DRISCA_REPOSITORY');
const base = process.env.VITEPRESS_BASE || '/DRISCA/';
const group = (directory, text) => ({
  text,
  items: readdirSync(resolve(root, 'docs', directory))
    .filter((file) => file.endsWith('.md'))
    .sort((a, b) => a.localeCompare(b, 'zh-CN'))
    .map((file) => {
      const content = readFileSync(resolve(root, 'docs', directory, file), 'utf8');
      const title = content.match(/^#\s+(.+)$/m)?.[1];
      if (!title) throw new Error(`文档缺少标题: ${directory}/${file}`);
      return { text: title.replace(/`/g, ''), link: `/${directory}/${basename(file, '.md')}` };
    }),
});
export default withMermaid(defineConfig({
  lang: 'zh-CN', title: 'DRISCA', description: '基于 CARLA 的驾驶行为研究实验平台', base,
  srcDir: resolve(root, '.github/docs-site/content'),
  outDir: resolve(root, '.local/docs-site/dist'),
  cacheDir: resolve(root, '.local/docs-site/cache'),
  mermaid: { theme: 'base', themeVariables: { primaryColor: '#e8f1fa', primaryTextColor: '#18324c', primaryBorderColor: '#668bad', lineColor: '#668bad', fontFamily: 'Segoe UI, Microsoft YaHei, sans-serif' } },
  head: [['link', { rel: 'icon', type: 'image/png', href: `${base}assets/icon.png` }]],
  themeConfig: {
    logo: '/assets/icon.png',
    nav: [{ text: '使用指南', link: '/guide/01-QuickStart' }, { text: '设计文档', link: '/design/01-Architecture' }],
    sidebar: [group('guide', '使用指南'), group('design', '设计文档')],
    outline: { level: [2, 3], label: '本页内容' },
    docFooter: { prev: '上一页', next: '下一页' },
    sidebarMenuLabel: '文档目录', returnToTopLabel: '返回顶部',
    search: { provider: 'local' },
  },
}));
