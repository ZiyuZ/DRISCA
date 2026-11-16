# 管理端交互原型

直接打开 `index.html`。样式和运行库已保存在 `vendor/`，可离线浏览。

原型记录已确认的管理端布局与操作流程，页面内的数据和操作保存在浏览器内存中。正式实现依据 [管理端设计](../../docs/design/04-LauncherDesign.md) 和 [前后端通信](../../docs/design/10-LauncherWeb.md)，前端源码放在根目录 `frontend/`。

`index.html` 保存界面结构，`app.css` 保存主题和业务布局，`app.js` 保存交互状态。通用组件使用 Basecoat 的标准 Dialog、Button、Tooltip、Switch、Tabs、Command 与 Toast；相机画布和拖拽属于业务交互。

正式前端使用 React、TypeScript、Vite、Tailwind CSS 和 shadcn/ui，由 Bun 管理。迁移时保留本原型的页面顺序、紧凑布局、状态反馈与交互约定。

第三方资源和许可见 [THIRD_PARTY.md](./THIRD_PARTY.md)。
