export const FIELD_LABELS: Record<string, Record<string, string>> = {
  tailscale: {
    oauthclientid: 'OAuth Client ID',
    oauthclientsecret: 'OAuth Client Secret',
    tailnet: 'Tailnet',
    apikey: 'API Key',
  },
  terraform: {
    cloudtoken: 'Cloud Token',
    cloudorganization: 'Cloud Organization',
  },
  cloudflare: {
    apitoken: 'API Token',
    accountid: 'Account ID',
    zoneid: 'Zone ID',
  },
  github: {
    pat: 'Personal Access Token',
    patsecretswrite: 'PAT (Secrets Write)',
    repo: 'Repository (org/repo)',
  },
  console: {
    username: 'Username',
    password: 'Password',
  },
  ansible: {
    vaultpassword: 'Vault Password',
  },
  bws: {
    projectid: 'Project ID',
  },
}

export const CATEGORY_LABELS: Record<string, string> = {
  console: 'Console',
  tailscale: 'Tailscale',
  terraform: 'Terraform',
  cloudflare: 'Cloudflare',
  github: 'GitHub',
  ansible: 'Ansible',
  bws: 'BWS',
}

export const CATEGORY_DESCRIPTIONS: Record<string, string> = {
  console: 'Admin credentials — SSH login and sudo user for all VMs',
  tailscale: 'Mesh VPN for secure access to VMs from anywhere',
  terraform: 'Infrastructure-as-code state management',
  cloudflare: 'DNS, tunnel, and origin certificate automation via Cloudflare API',
  github: 'Workflow triggers and self-hosted runner registration',
  ansible: 'Vault password for encrypting sensitive playbook variables',
  bws: 'Bitwarden Secrets Manager project settings',
}

export const INITIAL_FORM = {
  tailscale: { oauthclientid: '', oauthclientsecret: '', tailnet: '', apikey: '' },
  terraform: { cloudtoken: '', cloudorganization: '' },
  cloudflare: { apitoken: '', accountid: '', zoneid: '' },
  github: { pat: '', patsecretswrite: '', repo: '' },
  console: { username: '', password: '' },
  ansible: { vaultpassword: '' },
  bws: { projectid: '' },
}
