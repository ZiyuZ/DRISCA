export { zhCN } from "./zh-CN";
export type { LocaleMessages } from "./zh-CN";

type PlaceholderKeys<T extends string> =
  T extends `${string}{${infer Key}}${infer Rest}` ? Key | PlaceholderKeys<Rest> : never;
type TemplateValue = string | number | boolean | null | undefined;

/** 参数名由模板推导，保持与 JavaScript 模板字符串相同的数值转换语义。 */
export function format<const T extends string>(template: T, values: Record<PlaceholderKeys<T>, TemplateValue>): string {
  return template.replace(/\{([^{}]+)\}/g, (_, key: PlaceholderKeys<T>) => String(values[key]));
}
