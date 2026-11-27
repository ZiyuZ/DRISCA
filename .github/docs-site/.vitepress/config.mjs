import { defineConfig } from 'vitepress';
import { withMermaid } from 'vitepress-mermaid-viewer';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';

const root = process.env.DRISCA_REPOSITORY || resolve(import.meta.dirname, '../../..');
const docsDir = resolve(root, 'docs');
const siteNodeModules = resolve(import.meta.dirname, '../node_modules');
const base = process.env.VITEPRESS_BASE || '/DRISCA/';

const group = (directory, text) => {
  const dir = resolve(docsDir, directory);
  if (!existsSync(dir)) return [{ text, items: [] }];
  const items = readdirSync(dir)
    .filter((file) => file.endsWith('.md'))
    .sort((a, b) => a.localeCompare(b, 'zh-CN'))
    .map((file) => {
      const content = readFileSync(resolve(dir, file), 'utf8');
      const title = content.match(/^#\s+(.+)$/m)?.[1];
      if (!title) throw new Error(`文档缺少一级标题: ${directory}/${file}`);
      return {
        text: title.replace(/`/g, '').trim(),
        link: `/${directory}/${basename(file, '.md')}`,
      };
    });
  return [{ text, items }];
};

export default withMermaid(
  defineConfig({
    lang: 'zh-CN',
    title: 'DRISCA',
    description: '基于 CARLA 的驾驶行为研究实验平台',
    base,
    srcDir: docsDir,
    outDir: resolve(root, '.local/docs-site/dist'),
    cacheDir: resolve(root, '.local/docs-site/cache'),
    lastUpdated: true,
    markdown: {
      config(md) {
        const defaultImage = md.renderer.rules.image;
        md.renderer.rules.image = (tokens, idx, options, env, self) => {
          const token = tokens[idx];
          const rendered = defaultImage
            ? defaultImage(tokens, idx, options, env, self)
            : self.renderToken(tokens, idx, options);
          const alt = token.content?.trim();
          if (!alt) return rendered;
          const caption = md.utils.escapeHtml(alt);
          return `<span class="drisca-figure">${rendered}<span class="drisca-figcaption">${caption}</span></span>`;
        };
      },
    },
    vite: {
      resolve: {
        alias: [
          { find: /^vue\/server-renderer$/, replacement: resolve(siteNodeModules, 'vue/server-renderer') },
          { find: /^vue$/, replacement: resolve(siteNodeModules, 'vue') },
        ],
      },
      server: {
        fs: { allow: [root] },
      },
    },
    mermaid: {
      theme: 'base',
      themeVariables: {
        primaryColor: '#e8f1fa',
        primaryTextColor: '#18324c',
        primaryBorderColor: '#668bad',
        lineColor: '#668bad',
        fontFamily: 'Segoe UI, Microsoft YaHei, sans-serif',
      },
    },
    head: [['link', { rel: 'icon', type: 'image/png', href: `${base}icon.png` }]],
    themeConfig: {
      logo: '/icon.png',
      nav: [
        { text: '使用指南', link: '/guide/01-QuickStart', activeMatch: '/guide/' },
        { text: '构建与部署', link: '/deploy/01-CarlaSourceAndPatch', activeMatch: '/deploy/' },
        { text: '系统设计', link: '/design/01-Architecture', activeMatch: '/design/' },
      ],
      sidebar: {
        '/guide/': group('guide', '使用指南'),
        '/deploy/': group('deploy', '构建与部署'),
        '/design/': group('design', '系统设计'),
      },
      outline: { level: [2, 3], label: '本页目录' },
      docFooter: { prev: '上一页', next: '下一页' },
      lastUpdated: { text: '最后更新' },
      sidebarMenuLabel: '菜单',
      returnToTopLabel: '返回顶部',
      darkModeSwitchLabel: '外观',
      lightModeSwitchTitle: '切换到浅色模式',
      darkModeSwitchTitle: '切换到深色模式',
      search: {
        provider: 'local',
        options: {
          translations: {
            button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
            modal: {
              noResultsText: '未找到相关结果',
              resetButtonTitle: '清除查询条件',
              footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' },
            },
          },
        },
      },
    },
  }),
);
