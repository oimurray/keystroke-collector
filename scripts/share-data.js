#!/usr/bin/env node

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const projectDir = path.resolve(__dirname, '..');
const usage = `
Usage: npm run share -- [options]

Collect Pxx_Sn.csv and Pxx_Sn_meta.json pairs, copy them to data/<username>/,
commit that directory, then pull --rebase and push it.

Options:
  --source <dir>  Directory containing exported files (default: ~/Downloads)
  --user <name>   Folder owner (default: git user.name, then OS username)
  --no-push       Copy and commit locally without pulling or pushing
  --dry-run       Show what would happen without changing files or Git
  -h, --help      Show this help
`.trim();

function fail(message) {
  throw new Error(message);
}

function parseArgs(args) {
  const options = {
    source: path.join(os.homedir(), 'Downloads'),
    user: null,
    push: true,
    dryRun: false,
    help: false,
  };
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--source' || arg === '--user') {
      const value = args[++i];
      if (!value || value.startsWith('--')) fail(`${arg} requires a value.`);
      options[arg.slice(2)] = value;
    } else if (arg === '--no-push') {
      options.push = false;
    } else if (arg === '--dry-run') {
      options.dryRun = true;
    } else if (arg === '-h' || arg === '--help') {
      options.help = true;
    } else {
      fail(`Unknown option: ${arg}\n\n${usage}`);
    }
  }
  options.source = path.resolve(options.source);
  return options;
}

function git(repo, args, { allowFailure = false, quiet = false } = {}) {
  const result = spawnSync('git', args, {
    cwd: repo,
    encoding: 'utf8',
    stdio: quiet ? 'pipe' : ['inherit', 'pipe', 'pipe'],
  });
  if (result.error) fail(`Could not run Git: ${result.error.message}`);
  if (result.status !== 0 && !allowFailure) {
    const detail = (result.stderr || result.stdout || '').trim();
    fail(`git ${args.join(' ')} failed.${detail ? `\n${detail}` : ''}`);
  }
  return result;
}

function gitOutput(repo, args, allowFailure = false) {
  return git(repo, args, { allowFailure, quiet: true }).stdout.trim();
}

function usernameSlug(value) {
  const slug = value.normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^\p{Letter}\p{Number}]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
    .replace(/-+$/g, '');
  if (!slug) fail('The username must contain at least one letter or number.');
  if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i.test(slug)) {
    fail(`"${slug}" is a reserved Windows folder name; use --user with another name.`);
  }
  return slug;
}

function findExports(source) {
  let entries;
  try {
    entries = fs.readdirSync(source, { withFileTypes: true });
  } catch (error) {
    fail(`Cannot read source directory ${source}: ${error.message}`);
  }

  const pairs = new Map();
  for (const entry of entries) {
    if (!entry.isFile()) continue;
    const match = entry.name.match(/^(P\d{2}_S\d+)(\.csv|_meta\.json)$/);
    if (!match) continue;
    const pair = pairs.get(match[1]) || {};
    pair[match[2] === '.csv' ? 'csv' : 'meta'] = path.join(source, entry.name);
    pairs.set(match[1], pair);
  }
  if (!pairs.size) {
    fail(`No exported sessions found in ${source}. Expected files such as P01_S1.csv and P01_S1_meta.json.`);
  }

  for (const [base, pair] of pairs) {
    if (!pair.csv || !pair.meta) {
      fail(`${base} is incomplete: both ${base}.csv and ${base}_meta.json are required.`);
    }
    let metadata;
    try {
      metadata = JSON.parse(fs.readFileSync(pair.meta, 'utf8'));
    } catch (error) {
      fail(`Cannot parse ${pair.meta}: ${error.message}`);
    }
    if (`${metadata.participant_id}_${metadata.session_id}` !== base) {
      fail(`${pair.meta} does not match its filename (${base}).`);
    }
  }
  return pairs;
}

function destinationFor(repo, options) {
  const configuredName = options.user || gitOutput(repo, ['config', 'user.name'], true) || os.userInfo().username;
  const slug = usernameSlug(configuredName.trim());
  return { slug, dir: path.join(repo, 'data', slug) };
}

function copyExports(pairs, destination, dryRun) {
  if (!dryRun) fs.mkdirSync(destination, { recursive: true });
  let copied = 0;
  let unchanged = 0;
  for (const [base, pair] of [...pairs].sort(([a], [b]) => a.localeCompare(b))) {
    for (const [kind, extension] of [['csv', '.csv'], ['meta', '_meta.json']]) {
      const from = pair[kind];
      const to = path.join(destination, base + extension);
      if (fs.existsSync(to)) {
        if (!fs.readFileSync(from).equals(fs.readFileSync(to))) {
          fail(`${to} already exists with different content. Refusing to overwrite recorded data.`);
        }
        unchanged++;
        continue;
      }
      console.log(`${dryRun ? 'Would copy' : 'Copy'} ${from} -> ${to}`);
      if (!dryRun) fs.copyFileSync(from, to, fs.constants.COPYFILE_EXCL);
      copied++;
    }
  }
  return { copied, unchanged };
}

function remoteFor(repo, branch) {
  const remote = gitOutput(repo, ['config', `branch.${branch}.remote`], true) || 'origin';
  const mergeRef = gitOutput(repo, ['config', `branch.${branch}.merge`], true);
  const remoteBranch = mergeRef.startsWith('refs/heads/')
    ? mergeRef.slice('refs/heads/'.length)
    : branch;
  const remotes = gitOutput(repo, ['remote']).split(/\r?\n/).filter(Boolean);
  if (!remotes.includes(remote)) {
    fail(`Git remote "${remote}" does not exist. Add it first, for example: git remote add origin <repository-url>`);
  }
  return { remote, remoteBranch };
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    console.log(usage);
    return;
  }

  const repo = gitOutput(projectDir, ['rev-parse', '--show-toplevel']);
  const pairs = findExports(options.source);
  const { slug, dir } = destinationFor(repo, options);
  const relativeDir = path.relative(repo, dir).split(path.sep).join('/');
  console.log(`Sharing ${pairs.size} session(s) as ${slug} in ${relativeDir}/`);

  const result = copyExports(pairs, dir, options.dryRun);
  console.log(`${result.copied} new file(s), ${result.unchanged} unchanged file(s).`);
  if (options.dryRun) {
    console.log(`Dry run: would commit ${relativeDir}/ only${options.push ? ', pull --rebase, and push' : ''}.`);
    return;
  }
  if (!result.copied) {
    console.log('No new data; nothing to commit or push.');
    return;
  }

  let pushTarget;
  if (options.push && !options.dryRun) {
    const branch = gitOutput(repo, ['symbolic-ref', '--quiet', '--short', 'HEAD'], true);
    if (!branch) fail('Cannot push from a detached HEAD. Check out a branch first.');
    pushTarget = remoteFor(repo, branch);
  }

  git(repo, ['add', '--', relativeDir]);
  const staged = git(repo, ['diff', '--cached', '--quiet', '--', relativeDir], { allowFailure: true, quiet: true });
  if (staged.status === 0) {
    console.log('No new data; nothing to commit or push.');
    return;
  }
  if (staged.status !== 1) fail('Could not inspect the staged data.');

  git(repo, ['commit', '--only', '-m', `Add keystroke data for ${slug}`, '--', relativeDir]);
  console.log(`Committed ${relativeDir}/. Other changed files were not included.`);

  if (options.push) {
    const { remote, remoteBranch } = pushTarget;
    try {
      git(repo, ['pull', '--rebase', '--autostash', remote, remoteBranch]);
      git(repo, ['push', '-u', remote, `HEAD:${remoteBranch}`]);
    } catch (error) {
      fail(`${error.message}\nYour data commit is safe locally. Resolve any Git conflict, then run "git rebase --continue" and "git push".`);
    }
    console.log(`Pushed ${relativeDir}/ to ${remote}/${remoteBranch}.`);
  } else {
    console.log('Local commit created; pull and push were skipped.');
  }
}

try {
  main();
} catch (error) {
  console.error(`Share failed: ${error.message}`);
  process.exitCode = 1;
}
