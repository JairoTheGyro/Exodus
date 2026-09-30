// Workshop exposes one bounded artifact tool; generated code is never executed here.
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {writeFile, rm} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {spawn} from 'node:child_process';
const upstream = createRequire('/usr/local/lib/node_modules/@deepseek-ai/dsh/package.json');
const {defineTool} = await import(pathToFileURL(upstream.resolve('@deepseek-ai/dsh-tools')));
export const name = 'exodus-workshop-tools';
export const inject = ['tools', 'systemPrompt'];

export async function checkSource(source) {
  const issues = [];
  if (Buffer.byteLength(source) > 200000) return ['Keep this app below 200 KB.'];
  if (!/<html[\s>]/i.test(source) || !/<\/html>\s*$/i.test(source)) issues.push('Return a complete HTML document, including </html>.');
  if (/<(?:iframe|object|embed|base)\b/i.test(source)) issues.push('Embedded pages and external navigation are not supported.');
  if (/<(?:script|link)\b[^>]*(?:src|href)\s*=/i.test(source)) issues.push('Keep scripts and styles inline; no external dependencies.');
  const scripts = [...source.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi)];
  if (scripts.length > 30) return ['Use at most 30 inline scripts.'];
  for (const [index, match] of scripts.entries()) {
    const type = /\btype\s*=\s*["']([^"']*)["']/i.exec(match[1])?.[1];
    if (type && !['module', 'text/javascript', 'application/javascript'].includes(type)) continue;
    // --check parses syntax only. It does not run the submitted JavaScript.
    const issue = await new Promise(resolve => {
      const child = spawn(process.execPath, ['--check', `--input-type=${type === 'module' ? 'module' : 'commonjs'}`], {stdio: ['pipe', 'ignore', 'pipe'], env: {PATH: process.env.PATH}});
      let message = '';
      child.stderr.on('data', b => { if (message.length < 4000) message += b; });
      child.stdin.on('error', () => {});
      child.stdin.end(match[2]);
      const timer = setTimeout(() => child.kill('SIGKILL'), 3000);
      child.once('error', () => { clearTimeout(timer); resolve('Syntax checker unavailable.'); });
      child.once('close', code => { clearTimeout(timer); resolve(code === 0 ? null : `Script ${index + 1}: ${message.slice(0, 1000) || 'syntax check failed'}`); });
    });
    if (issue) issues.push(issue);
  }
  return issues;
}

export function apply(ctx) {
  const instructions = readFileSync(process.env.EXODUS_WORKSHOP_INSTRUCTIONS, 'utf8');
  ctx.systemPrompt.section({name: 'exodus-workshop', order: 0, text: instructions, interpolate: false, complete: true});
  // Visibility filtering and an independent execution guard: prompts cannot grant tools.
  ctx.on('system-prompt/assemble', async (assembly, context, next) => {
    const result = await next();
    result.tools = result.tools.filter(t => t.name === 'submit_workshop_app');
    return result;
  });
  let calls = 0;
  ctx.tools.guard(exec => exec.name !== 'submit_workshop_app' ? 'Only Workshop app submission is permitted.' :
    ++calls > 12 ? 'Workshop revision limit reached. Stop and report the failure.' : undefined);
  ctx.tools.register(defineTool({
    name: 'submit_workshop_app',
    description: 'Submit the complete single-file HTML app for basic structure and JavaScript syntax checks. If issues are returned, fix them and resubmit. Successful checks store the candidate for Workshop; they do not prove correctness or safety. Finish after a successful submission.',
    parameters: {source: {type: 'string', required: true, description: 'Complete HTML document with inline styles and scripts.'}},
    output: {schema: {type: 'string'}, render: (_args, value) => [{type: 'text', text: value}]},
    async execute({source}) {
      // A rejected later revision must not accidentally return an earlier candidate.
      await rm(process.env.EXODUS_WORKSHOP_RESULT, {force: true});
      const issues = await checkSource(source);
      if (issues.length) return JSON.stringify({accepted: false, issues});
      await writeFile(process.env.EXODUS_WORKSHOP_RESULT, source, {mode: 0o600});
      return JSON.stringify({accepted: true, checks: ['HTML document structure', 'Inline JavaScript syntax'], note: 'Behavior, accessibility and security still require testing.'});
    },
  }));
  ctx.provide('workshopReady', true);
}
