"""Build-tool / package-manager command detection (``CodeFields.build_commands``).

The new ``CodeFields.build_commands`` slot captures recipe lines
like ``$ npm install`` / ``cargo build --release`` /
``docker build -t app .`` found in code snippets and terminal
captures. Each entry is a ``{"tool", "command"}`` dict.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import enrich_code, extract_build_commands

# ---- Node ecosystem -------------------------------------------


def test_npm_install():
    out = extract_build_commands("$ npm install")
    assert out == [{"tool": "npm", "command": "npm install"}]


def test_npm_run_subcommand():
    out = extract_build_commands("$ npm run build")
    assert out == [{"tool": "npm", "command": "npm run build"}]


def test_npm_test():
    out = extract_build_commands("npm test")
    assert out == [{"tool": "npm", "command": "npm test"}]


def test_yarn_add_versioned():
    out = extract_build_commands("$ yarn add react@18")
    assert out == [{"tool": "yarn", "command": "yarn add react@18"}]


def test_pnpm_run_build():
    out = extract_build_commands("pnpm run build")
    assert out == [{"tool": "pnpm", "command": "pnpm run build"}]


def test_bun_install():
    out = extract_build_commands("$ bun install")
    assert out == [{"tool": "bun", "command": "bun install"}]


def test_npx_bare_ok():
    """``npx`` accepts bare invocation."""
    out = extract_build_commands("$ npx create-react-app myapp")
    assert out == [{"tool": "npx", "command": "npx create-react-app myapp"}]


# ---- Python ecosystem -----------------------------------------


def test_pip_install_requirements():
    out = extract_build_commands("$ pip install -r requirements.txt")
    assert out == [
        {"tool": "pip", "command": "pip install -r requirements.txt"}
    ]


def test_pip3_install():
    out = extract_build_commands("$ pip3 install httpx")
    assert out == [{"tool": "pip3", "command": "pip3 install httpx"}]


def test_pipx_install():
    out = extract_build_commands("$ pipx install black")
    assert out == [{"tool": "pipx", "command": "pipx install black"}]


def test_poetry_add():
    out = extract_build_commands("$ poetry add httpx")
    assert out == [{"tool": "poetry", "command": "poetry add httpx"}]


def test_uv_sync():
    out = extract_build_commands("$ uv sync")
    assert out == [{"tool": "uv", "command": "uv sync"}]


def test_uv_add():
    out = extract_build_commands("$ uv add httpx")
    assert out == [{"tool": "uv", "command": "uv add httpx"}]


def test_conda_create():
    out = extract_build_commands("$ conda create -n env python=3.11")
    assert out == [
        {"tool": "conda", "command": "conda create -n env python=3.11"}
    ]


def test_pipenv_install():
    out = extract_build_commands("$ pipenv install")
    assert out == [{"tool": "pipenv", "command": "pipenv install"}]


# ---- Ruby -----------------------------------------------------


def test_bundle_install():
    out = extract_build_commands("$ bundle install")
    assert out == [{"tool": "bundle", "command": "bundle install"}]


def test_gem_install_rails():
    out = extract_build_commands("$ gem install rails")
    assert out == [{"tool": "gem", "command": "gem install rails"}]


# ---- Rust / Go ------------------------------------------------


def test_cargo_build_release():
    out = extract_build_commands("$ cargo build --release")
    assert out == [{"tool": "cargo", "command": "cargo build --release"}]


def test_cargo_install_ripgrep():
    out = extract_build_commands("cargo install ripgrep")
    assert out == [{"tool": "cargo", "command": "cargo install ripgrep"}]


def test_rustup_install():
    out = extract_build_commands("$ rustup install stable")
    assert out == [{"tool": "rustup", "command": "rustup install stable"}]


def test_go_build_all():
    out = extract_build_commands("$ go build ./...")
    assert out == [{"tool": "go", "command": "go build ./..."}]


def test_go_get():
    out = extract_build_commands("$ go get github.com/foo/bar")
    assert out == [{"tool": "go", "command": "go get github.com/foo/bar"}]


# ---- PHP / Java / .NET ---------------------------------------


def test_composer_require():
    out = extract_build_commands("$ composer require monolog/monolog")
    assert out == [
        {"tool": "composer", "command": "composer require monolog/monolog"}
    ]


def test_mvn_clean_install():
    out = extract_build_commands("$ mvn clean install")
    assert out == [{"tool": "mvn", "command": "mvn clean install"}]


def test_gradle_wrapper():
    out = extract_build_commands("$ gradle wrapper")
    assert out == [{"tool": "gradle", "command": "gradle wrapper"}]


def test_gradle_build():
    out = extract_build_commands("$ gradle build")
    assert out == [{"tool": "gradle", "command": "gradle build"}]


def test_sbt_compile():
    out = extract_build_commands("$ sbt compile")
    assert out == [{"tool": "sbt", "command": "sbt compile"}]


def test_dotnet_restore():
    out = extract_build_commands("$ dotnet restore")
    assert out == [{"tool": "dotnet", "command": "dotnet restore"}]


def test_dotnet_build():
    out = extract_build_commands("$ dotnet build --configuration Release")
    assert out == [
        {"tool": "dotnet", "command": "dotnet build --configuration Release"}
    ]


def test_mvnw_wrapper_remaps_to_mvn():
    out = extract_build_commands("$ ./mvnw clean install")
    assert out == [{"tool": "mvn", "command": "./mvnw clean install"}]


def test_gradlew_wrapper_remaps_to_gradle():
    out = extract_build_commands("$ ./gradlew build")
    assert out == [{"tool": "gradle", "command": "./gradlew build"}]


# ---- Make / task runners -------------------------------------


def test_make_bare():
    """``make`` with no target is meaningful (runs first Makefile target)."""
    out = extract_build_commands("$ make")
    assert out == [{"tool": "make", "command": "make"}]


def test_make_test_target():
    out = extract_build_commands("$ make test")
    assert out == [{"tool": "make", "command": "make test"}]


def test_just_recipe():
    out = extract_build_commands("$ just deploy")
    assert out == [{"tool": "just", "command": "just deploy"}]


def test_task_runner():
    out = extract_build_commands("$ task build")
    assert out == [{"tool": "task", "command": "task build"}]


# ---- Containers / orchestration ------------------------------


def test_docker_build():
    out = extract_build_commands("$ docker build -t app .")
    assert out == [{"tool": "docker", "command": "docker build -t app ."}]


def test_docker_compose_up():
    out = extract_build_commands("$ docker compose up -d")
    assert out == [
        {"tool": "docker", "command": "docker compose up -d"}
    ]


def test_podman_run():
    out = extract_build_commands("$ podman run hello-world")
    assert out == [{"tool": "podman", "command": "podman run hello-world"}]


def test_kubectl_apply():
    out = extract_build_commands("$ kubectl apply -f deploy.yaml")
    assert out == [
        {"tool": "kubectl", "command": "kubectl apply -f deploy.yaml"}
    ]


def test_kubectl_get_pods():
    out = extract_build_commands("$ kubectl get pods")
    assert out == [{"tool": "kubectl", "command": "kubectl get pods"}]


def test_helm_install():
    out = extract_build_commands("$ helm install app ./chart")
    assert out == [
        {"tool": "helm", "command": "helm install app ./chart"}
    ]


def test_terraform_apply():
    out = extract_build_commands("$ terraform apply -auto-approve")
    assert out == [
        {"tool": "terraform", "command": "terraform apply -auto-approve"}
    ]


def test_terraform_init():
    out = extract_build_commands("$ terraform init")
    assert out == [{"tool": "terraform", "command": "terraform init"}]


# ---- OS package managers -------------------------------------


def test_brew_install():
    out = extract_build_commands("$ brew install ripgrep")
    assert out == [{"tool": "brew", "command": "brew install ripgrep"}]


def test_apt_install():
    out = extract_build_commands("# apt install curl")
    assert out == [{"tool": "apt", "command": "apt install curl"}]


def test_apt_get_update():
    out = extract_build_commands("# apt-get update")
    assert out == [{"tool": "apt-get", "command": "apt-get update"}]


def test_yum_install():
    out = extract_build_commands("# yum install httpd")
    assert out == [{"tool": "yum", "command": "yum install httpd"}]


def test_dnf_install():
    out = extract_build_commands("# dnf install httpd")
    assert out == [{"tool": "dnf", "command": "dnf install httpd"}]


def test_pacman_sync():
    out = extract_build_commands("# pacman -Syu")
    assert out == [{"tool": "pacman", "command": "pacman -Syu"}]


def test_apk_add():
    out = extract_build_commands("$ apk add curl")
    assert out == [{"tool": "apk", "command": "apk add curl"}]


def test_gh_repo_clone():
    out = extract_build_commands("$ gh repo clone foo/bar")
    assert out == [{"tool": "gh", "command": "gh repo clone foo/bar"}]


# ---- Shell prompt variants ------------------------------------


def test_bash_dollar_prompt():
    out = extract_build_commands("$ npm install")
    assert out == [{"tool": "npm", "command": "npm install"}]


def test_root_hash_prompt():
    out = extract_build_commands("# pip install httpx")
    assert out == [{"tool": "pip", "command": "pip install httpx"}]


def test_powershell_full_prompt():
    out = extract_build_commands("PS C:\\code> dotnet restore")
    assert out == [{"tool": "dotnet", "command": "dotnet restore"}]


def test_powershell_bare_prompt():
    out = extract_build_commands("PS> dotnet build")
    assert out == [{"tool": "dotnet", "command": "dotnet build"}]


def test_conda_env_prompt():
    out = extract_build_commands("(myenv) $ pip install httpx")
    assert out == [{"tool": "pip", "command": "pip install httpx"}]


def test_user_host_prompt():
    out = extract_build_commands("user@host:~/project$ npm install")
    assert out == [{"tool": "npm", "command": "npm install"}]


def test_bracket_prompt():
    out = extract_build_commands("[user@host project]$ make")
    assert out == [{"tool": "make", "command": "make"}]


def test_generic_arrow_prompt():
    out = extract_build_commands("> npm install")
    assert out == [{"tool": "npm", "command": "npm install"}]


def test_no_prompt_line_start():
    """A bare line with no prompt still tags as long as the tool is first."""
    out = extract_build_commands("npm install")
    assert out == [{"tool": "npm", "command": "npm install"}]


# ---- False-positive defences ---------------------------------


def test_mid_sentence_npm_install_rejected():
    """``npm install`` mid-sentence does NOT fire (must be at line start)."""
    out = extract_build_commands("I use npm install for this project")
    assert out == []


def test_bare_npm_no_subcommand_rejected():
    """``npm`` alone has no subcommand; rejected."""
    out = extract_build_commands("npm")
    assert out == []


def test_bare_pip_no_subcommand_rejected():
    out = extract_build_commands("$ pip")
    assert out == []


def test_unknown_tool_rejected():
    out = extract_build_commands("$ foobar build")
    assert out == []


def test_empty_text():
    assert extract_build_commands("") == []


def test_blank_lines_skipped():
    out = extract_build_commands("\n\n\n")
    assert out == []


# ---- Multiple commands, ordering, dedupe ---------------------


def test_multiple_commands_in_order():
    code = (
        "$ npm install\n"
        "$ npm run build\n"
        "$ npm test\n"
    )
    out = extract_build_commands(code)
    assert len(out) == 3
    assert all(e["tool"] == "npm" for e in out)


def test_mixed_tools_in_one_recipe():
    code = (
        "$ npm install\n"
        "$ cargo build --release\n"
        "$ docker build -t app .\n"
        "$ kubectl apply -f deploy.yaml\n"
    )
    out = extract_build_commands(code)
    tools = [e["tool"] for e in out]
    assert tools == ["npm", "cargo", "docker", "kubectl"]


def test_dedupe_identical_commands():
    code = "$ npm install\n$ npm install"
    out = extract_build_commands(code)
    assert len(out) == 1


def test_dedupe_keeps_different_args():
    code = "$ npm install foo\n$ npm install bar"
    out = extract_build_commands(code)
    assert len(out) == 2


# ---- Cap enforcement -----------------------------------------


def test_cap_at_50():
    code = "\n".join(f"$ npm install pkg{i}" for i in range(80))
    out = extract_build_commands(code)
    assert len(out) == 50


# ---- enrich_code integration ---------------------------------


def test_enrich_code_populates_build_commands():
    text = (
        "# README\n"
        "$ npm install\n"
        "$ npm run build\n"
        "$ docker build -t app .\n"
    )
    out = enrich_code(None, OCRResult(text=text))
    assert len(out.build_commands) == 3
    tools = [e["tool"] for e in out.build_commands]
    assert tools == ["npm", "npm", "docker"]


def test_enrich_code_preserves_caller_build_commands():
    existing = CodeFields(
        build_commands=[{"tool": "manual", "command": "from caller"}]
    )
    out = enrich_code(existing, OCRResult(text="$ npm install"))
    assert out.build_commands == [{"tool": "manual", "command": "from caller"}]


def test_enrich_code_no_commands_empty_list():
    text = "def foo():\n    return 1"
    out = enrich_code(None, OCRResult(text=text))
    assert out.build_commands == []


# ---- Whitespace robustness -----------------------------------


def test_extra_whitespace_collapsed():
    out = extract_build_commands("$   npm    install    react")
    assert out == [{"tool": "npm", "command": "npm install react"}]


def test_leading_whitespace_ok():
    out = extract_build_commands("    $ npm install")
    assert out == [{"tool": "npm", "command": "npm install"}]


def test_trailing_whitespace_stripped():
    out = extract_build_commands("$ npm install   ")
    assert out == [{"tool": "npm", "command": "npm install"}]
