import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("guard", Path(__file__).parents[1] / "security/secrets-guard/guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

FAKE_ENV_BASE = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}


class GuardTests(unittest.TestCase):
    def test_incident_and_denials(self):
        for command in [
            "ssh hsrpc-wsl 'cd ~/pfull && node -e \"console.log(process.env.DATABASE_URL)\"'",
            "ssh hsrpc-wsl 'set -a; . ~/pfull/prod.env; set +a; python3 -c \"import os; print(os.environ.get(\\\"DATABASE_URL\\\"))\"'",
            "bb config get BB_ACCOUNT_POOL_PARENT_TOKEN",
            "bb variables dump",
            "echo $BB_ACCOUNT_POOL_PARENT_TOKEN",
            "env", "printenv", "set", "export -p", "declare -x",
            "cat ~/pfull/prod.env", "sed -n '1,20p' .env.local",
            "base64 ~/pfull/prod.env", "base64 .env.local",
            "python3 -c \"from pathlib import Path; print(Path('~/.aws/credentials').read_text())\"",
            "openssl enc -base64 -in ~/.aws/credentials",
            "ls && openssl enc -base64 -in ~/.aws/credentials",
            "ls; openssl enc -base64 -in ~/.aws/credentials",
            "ls | openssl enc -base64 -in ~/.aws/credentials",
            "bash -c 'ls && openssl enc -base64 -in ~/.aws/credentials'",
            "ssh hsrpc-wsl 'ls && openssl enc -base64 -in ~/.aws/credentials'",
            'ls() { cat "$@"; }; ls ~/.aws/credentials',
            'ls() (cat "$@"); ls ~/.aws/credentials',
            "eval \"$(printf 'bHMpIHsgY2F0ICIkQCI7IH0=' | base64 -d)\"; ls ~/.aws/credentials",
            "e''val \"$(printf 'bHMpIHsgY2F0ICIkQCI7IH0=' | base64 -d)\"; ls ~/.aws/credentials",
            "x=; e${x}val \"$(printf 'bHMoKXsgY2F0ICIkQCI7IH0=' | base64 -d)\"; ls ~/.aws/credentials",
            "mongodb://fake:fake@host/db", "vercel env ls",
            "git config --get credential.helper",
            "x=1 env", "sudo env", "foo; set", "a && printenv", "ls\nset", "/usr/bin/env", "xargs printenv",
            "sudo -u root env", "nice -n 5 printenv", "xargs -I{} env", "stdbuf -o0 env", "command -p env",
            "sudo -u root nohup env", "FOO=1 sudo -E printenv",
        ]:
            self.assertTrue(guard.denied(command), command)

    def test_allowed(self):
        for command in [
            "ssh hsrpc-wsl 'cd ~/pfull && ./prodmongo.sh q.js'",
            "ssh hsrpc-wsl './prodmongo.sh q.js'",
            "set -a; . ~/pfull/prod.env; set +a; node script.js",
            "bb thread tell --message-file note.txt", "grep -c TOKEN .env",
            "grep BB_ACCOUNT_POOL_PARENT_TOKEN file", "git status", "pnpm lint", "ls -la",
        ]:
            self.assertFalse(guard.denied(command), command)

    def test_sql_set_in_heredoc_is_not_a_variable_dump(self):
        sql = "CREATE FUNCTION f() RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public AS $$ select 1 $$;"
        for command in [
            "cat > f.sql <<'SQL'\n" + sql + "\nSQL",
            "cat > f.sql <<'SQL'\n" + sql + "\nSQL\npsql -f f.sql",
            "echo ok && cat > f.sql <<'SQL'\nALTER ROLE r SET statement_timeout = 0;\nSQL",
        ]:
            self.assertFalse(guard.denied(command), command)

    def test_exact_output_scrubber(self):
        p=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        s=importlib.util.spec_from_file_location("scrubber",p); scrubber=importlib.util.module_from_spec(s); s.loader.exec_module(scrubber)
        fake="mongodb+srv://fake:fake@x"
        self.assertEqual(scrubber.redact(("out="+fake).encode(),[fake]),b"out=[MASKED]", "stdout exact-value redaction failed")
        self.assertEqual(scrubber.redact(("err="+fake).encode(),[fake]),b"err=[MASKED]", "stderr exact-value redaction failed")
        encoded=__import__('base64').b64encode(fake.encode())
        self.assertEqual(scrubber.redact(b"encoded="+encoded,[fake]),b"encoded=[MASKED]", "base64 transformed secret survived output redaction")

    def test_env_parser_masks_expansions_and_unquoted_comments(self):
        p=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        s=importlib.util.spec_from_file_location("scrubber_env_parser",p); scrubber=importlib.util.module_from_spec(s); s.loader.exec_module(scrubber)
        values=scrubber.parse_env("FILLER=12345\nFAKE_TOKEN=\"prefix${FILLER}\"\nFAKE_COMMENT_TOKEN=synthetic-token-123 # comment\n")
        self.assertIn("prefix12345",values,"shell-expanded fake token was not collected")
        self.assertIn("synthetic-token-123",values,"comment-trimmed fake token was not collected")

    def test_remote_mask_fetch_requires_actual_ssh_command(self):
        p=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        s=importlib.util.spec_from_file_location("scrubber_ssh_detection",p); scrubber=importlib.util.module_from_spec(s); s.loader.exec_module(scrubber)
        self.assertTrue(scrubber.has_hsrpc_ssh("cd ~/pfull && ssh -p 22 hsrpc-wsl './prodmongo.sh q.js'"))
        self.assertTrue(scrubber.has_hsrpc_ssh("bash -c 'ssh hsrpc-wsl ./prodmongo.sh'"))
        self.assertFalse(scrubber.has_hsrpc_ssh("echo 'ssh hsrpc-wsl is only documentation'"))
        self.assertFalse(scrubber.has_hsrpc_ssh("# ssh hsrpc-wsl cat ~/pfull/prod.env\nls"))

    def test_scrubs_values_loaded_from_command_sourced_env_file(self):
        scrubber_path=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        spec=importlib.util.spec_from_file_location("scrubber_paths",scrubber_path)
        scrubber=importlib.util.module_from_spec(spec); spec.loader.exec_module(scrubber)
        fake="mongodb+srv://fake:fake@x"
        with tempfile.TemporaryDirectory(prefix="secrets-guard-fake-") as temp:
            env_file=Path(temp) / "prod.env"
            env_file.write_text("FAKE_DB_URI="+fake+"\n")
            self.assertEqual(set(scrubber.env_mask_paths("cd "+shlex.quote(temp)+" && . prod.env")),{str(env_file)})
            command=("set -a; . "+shlex.quote(str(env_file))+"; set +a; python3 -c "+
                     shlex.quote("import os; raise RuntimeError(os.environ['FAKE_DB_URI'])"))
            env=dict(FAKE_ENV_BASE,HOME=temp,TMPDIR=temp)
            result=subprocess.run([sys.executable,str(scrubber_path),"--",command],cwd=temp,capture_output=True,env=env)
        combined=result.stdout+result.stderr
        self.assertFalse(fake.encode() in combined,"fake sourced value survived output redaction")
        self.assertIn(b"RuntimeError: [MASKED]",combined)
        self.assertNotEqual(result.returncode,0)

    def test_scrubs_base64_secret_loaded_from_sourced_env_file(self):
        scrubber_path=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        fake="mongodb+srv://fake-user:fake-password@fake.example/db"
        encoded=__import__('base64').b64encode(fake.encode())
        with tempfile.TemporaryDirectory(prefix="secrets-guard-base64-") as temp:
            env_file=Path(temp) / "prod.env"
            env_file.write_text("FAKE_DB_URI="+fake+"\n")
            app="import os,base64; raise RuntimeError(base64.b64encode(os.environ['FAKE_DB_URI'].encode()).decode())"
            command=("set -a; . "+shlex.quote(str(env_file))+"; set +a; python3 -c "+shlex.quote(app))
            env=dict(FAKE_ENV_BASE,HOME=temp,TMPDIR=temp)
            result=subprocess.run([sys.executable,str(scrubber_path),"--",command],cwd=temp,capture_output=True,env=env)
        combined=result.stdout+result.stderr
        self.assertNotIn(encoded,combined,"base64 transformed fake secret survived scrubber")
        self.assertIn(b"RuntimeError: [MASKED]",combined)
        self.assertNotEqual(result.returncode,0)

    def test_scrubs_values_loaded_from_cwd_dotenv_by_the_application(self):
        scrubber=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        fake="fake-token-value-123456"
        with tempfile.TemporaryDirectory(prefix="secrets-guard-dotenv-") as temp:
            workdir=Path(temp) / "project"
            workdir.mkdir()
            (workdir / ".env").write_text("FAKE_TOKEN="+fake+"\n")
            app="import os; from pathlib import Path; os.environ.update(dict(line.split('=',1) for line in Path('.env').read_text().splitlines())); raise RuntimeError(os.environ['FAKE_TOKEN'])"
            command="cd "+shlex.quote(str(workdir))+" && python3 -c "+shlex.quote(app)
            env=dict(FAKE_ENV_BASE,HOME=temp,TMPDIR=temp)
            result=subprocess.run([sys.executable,str(scrubber),"--",command],cwd=temp,capture_output=True,env=env)
        combined=result.stdout+result.stderr
        self.assertFalse(fake.encode() in combined,"fake dotenv value survived output redaction")
        self.assertIn(b"RuntimeError: [MASKED]",combined)
        self.assertNotEqual(result.returncode,0)

    def test_scrubs_shell_expansion_and_comment_values_from_sourced_file(self):
        scrubber=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        expanded="prefix12345"
        commented="synthetic-token-123"
        with tempfile.TemporaryDirectory(prefix="secrets-guard-env-expansion-") as temp:
            env_file=Path(temp)/"prod.env"
            env_file.write_text('FILLER=12345\nFAKE_TOKEN="prefix${FILLER}"\nFAKE_COMMENT_TOKEN=synthetic-token-123 # fake comment\n')
            app="import os; print(os.environ['FAKE_COMMENT_TOKEN']); raise RuntimeError(os.environ['FAKE_TOKEN'])"
            command=("set -a; . "+shlex.quote(str(env_file))+"; set +a; python3 -c "+shlex.quote(app))
            env=dict(FAKE_ENV_BASE,HOME=temp,TMPDIR=temp)
            result=subprocess.run([sys.executable,str(scrubber),"--",command],cwd=temp,capture_output=True,env=env)
        combined=result.stdout+result.stderr
        self.assertFalse(expanded.encode() in combined,"expanded fake value survived redaction")
        self.assertFalse(commented.encode() in combined,"commented fake value survived redaction")
        self.assertEqual(combined.count(b"[MASKED]"),2,"expected stdout and stderr values to be masked")

    def _load_scrubber(self, name):
        p=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        s=importlib.util.spec_from_file_location(name,p); scrubber=importlib.util.module_from_spec(s); s.loader.exec_module(scrubber)
        return scrubber

    def test_env_parser_masks_real_dotenv_lines_instead_of_failing(self):
        scrubber=self._load_scrubber("scrubber_real_dotenv")
        text=("# fake comment line\r\n"
              "\r\n"
              "FAKE_FROM=Fake Person <fake-person@example.invalid>\r\n"
              "export FAKE_EXPORTED_TOKEN=fake-exported-value-1\r\n"
              "FAKE_INLINE=fake-inline-value-12345 # fake trailing comment\r\n"
              "FAKE_STRAY=it's a fake-stray-quote value\r\n"
              "FAKE_DOLLAR=fake-dollar-value-123$\r\n"
              "this line is not dotenv fake-unparsed-word\r\n"
              "FAKE_PEM=\"-----BEGIN FAKE KEY-----\r\n"
              "Zm9vYmFyZmFrZQ=\r\n"
              "-----END FAKE KEY-----\"\r\n"
              "FAKE_AFTER_TOKEN=fake-after-value-123\r\n")
        shell_lines=("FAKE_STRAY=it's a fake-stray-quote value\r\n","this line is not dotenv fake-unparsed-word\r\n")
        for strict in (False,True):
            # A sourced file is shell: a stray quote or a non-assignment line fails closed there.
            values=scrubber.parse_env(text if not strict else
                                      "".join(l for l in text.splitlines(True) if l not in shell_lines),strict=strict)
            for expected in ("Fake Person <fake-person@example.invalid>","<fake-person@example.invalid>",
                             "fake-exported-value-1","fake-inline-value-12345",
                             "fake-dollar-value-123$","Zm9vYmFyZmFrZQ=","fake-after-value-123")+(
                             () if strict else ("fake-stray-quote","fake-unparsed-word")):
                self.assertIn(expected,values,"real dotenv line was not masked: "+expected)
            self.assertFalse(any("\r" in v for v in values),"CRLF leaked into a mask value")
        for line in shell_lines:
            with self.assertRaises(ValueError,msg=line):
                scrubber.parse_env(line,strict=True)

    def test_env_parser_dynamic_values_fail_closed_only_when_strict(self):
        scrubber=self._load_scrubber("scrubber_dynamic")
        for line in ("FAKE_A=$(echo fake)\n","FAKE_B=`echo fake`\n","FAKE_C=\"${FAKE_UNSET:?fake}\"\n",
                     "FAKE_D=fake words $(echo x)\n","echo $(fake)\n"):
            with self.assertRaises(ValueError,msg=line):
                scrubber.parse_env(line,strict=True)
            self.assertTrue(scrubber.parse_env(line),"non-strict parse should mask dynamic line: "+line)

    def test_sourced_env_shell_commands_fail_closed_without_output(self):
        scrubber=self._load_scrubber("scrubber_shell_lines")
        for line in ("cat fake-cred.txt\n","FAKE_X=a cat fake-cred.txt\n","FAKE_X=a; cat fake-cred.txt\n",
                     "FAKE_X=\"a\" cat fake-cred.txt\n","FAKE_X=\"a\nb\" ; cat fake-cred.txt\n",
                     "FAKE_X=a /bin/cat fake-cred.txt\n","FAKE_CMD=cat\nFAKE_X=a $FAKE_CMD fake-cred.txt\n",
                     "FAKE_X=a ca[t] fake-cred.txt\n","FAKE_X='a' FAKE_Y=b cat fake-cred.txt\n"):
            with self.assertRaises(ValueError,msg=line):
                scrubber.parse_env(line,strict=True)
            scrubber.parse_env(line)
        self.assertIn("Fake Person <fake@example.invalid>",
                      scrubber.parse_env("FAKE_FROM=Fake Person <fake@example.invalid>\nexport FAKE_FROM\n",strict=True))
        with tempfile.TemporaryDirectory() as directory:
            cred=Path(directory,"fake-cred.txt"); cred.write_text("FAKE-CREDENTIAL-CONTENTS-0001\n")
            for body in ("cat fake-cred.txt\n","FAKE_X=a cat fake-cred.txt\n"):
                env_file=Path(directory,"fake-sourced.env"); env_file.write_text(body)
                proc=subprocess.run(["/usr/bin/python3",str(Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"),"--",". ./fake-sourced.env; echo after"],
                                    cwd=directory,capture_output=True)
                self.assertEqual(proc.returncode,2,body)
                self.assertNotIn(b"FAKE-CREDENTIAL-CONTENTS",proc.stdout+proc.stderr)
                self.assertNotIn(b"after",proc.stdout)
            # Positional and special parameters come from the running shell: fail closed.
            for form in ("$1","$@","$*","$#","$?","$$","$!","$0","x$1y","\"$1\"","$[FAKE_N+1]"):
                with self.assertRaises(ValueError,msg=form):
                    scrubber.parse_env("FAKE_TOKEN="+form+"\n",strict=True)
                self.assertTrue(scrubber.parse_env("FAKE_TOKEN="+form+"\n"))
            env_file=Path(directory,"fake-sourced.env"); env_file.write_text("FAKE_TOKEN=$1\n")
            proc=subprocess.run(["/usr/bin/python3",str(Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"),"--",
                                 "set -- fake-positional-secret-0123; . ./fake-sourced.env; echo \"$FAKE_TOKEN\"; echo after"],
                                cwd=directory,capture_output=True)
            self.assertEqual(proc.returncode,2)
            self.assertNotIn(b"fake-positional-secret",proc.stdout+proc.stderr)
            self.assertNotIn(b"after",proc.stdout)
            # A shell function the command defines before sourcing is a command too.
            env_file=Path(directory,"fake-sourced.env"); env_file.write_text("FAKE_X=x fakeleak fake-cred.txt\n")
            proc=subprocess.run(["/usr/bin/python3",str(Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"),"--",
                                 "fakeleak(){ cat \"$1\"; }; . ./fake-sourced.env; echo after"],cwd=directory,capture_output=True)
            self.assertEqual(proc.returncode,2)
            self.assertNotIn(b"FAKE-CREDENTIAL-CONTENTS",proc.stdout+proc.stderr)
            self.assertNotIn(b"after",proc.stdout)
            # Bash process substitution runs its command while sourcing; it needs no separator.
            for form in ("<(cat fake-cred.txt >/dev/stderr)",">(cat fake-cred.txt >/dev/stderr)","a<(cat fake-cred.txt >/dev/stderr)"):
                with self.assertRaises(ValueError,msg=form):
                    scrubber.parse_env("FAKE_TOKEN="+form+"\n",strict=True)
                self.assertTrue(scrubber.parse_env("FAKE_TOKEN="+form+"\n"))
                env_file=Path(directory,"fake-sourced.env"); env_file.write_text("FAKE_TOKEN="+form+"\n")
                proc=subprocess.run(["/usr/bin/python3",str(Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"),"--",
                                     "set +o posix; . ./fake-sourced.env; echo after"],cwd=directory,capture_output=True)
                self.assertEqual(proc.returncode,2,form)
                self.assertNotIn(b"FAKE-CREDENTIAL-CONTENTS",proc.stdout+proc.stderr)
                self.assertNotIn(b"after",proc.stdout)
            self.assertIn("fake<(literal)value",scrubber.parse_env("FAKE_TOKEN='fake<(literal)value'\n",strict=True))

    def test_sourced_env_shell_state_class_fails_closed(self):
        # One table for every Bash construct whose value or side effect comes from the running
        # shell, not from the file. FAKE values only.
        scrubber=self._load_scrubber("scrubber_shell_state")
        names=("_ BASH_COMMAND BASH_ARGV BASH_ARGC BASH_SOURCE BASH_LINENO BASH_EXECUTION_STRING FUNCNAME LINENO "
               "RANDOM SRANDOM SECONDS EPOCHSECONDS EPOCHREALTIME PPID PWD OLDPWD SHLVL HISTCMD").split()
        block=["$"+n for n in names]+["${"+n+"}" for n in names]+["x$_ y","\"$_\"","${FAKE_SET:-$_}","${FAKE_SET:-$PWD}"]
        block+=["$0","$$","$!","$?","$-","$#","$@","$*","$1","${1}","\"$@\""]
        block+=["$(cat fake-cred.txt)","`cat fake-cred.txt`","x$(cat fake-cred.txt)y","$((1+2))","$[1+2]",
                "$((a[$(cat fake-cred.txt)]))"]
        block+=["${!FAKE_NAME}","${FAKE_SET:=fake}","${FAKE_SET@P}","${#FAKE_SET}","${FAKE_SET[@]}"]
        block+=["<(cat fake-cred.txt)",">(cat fake-cred.txt)","a<(cat fake-cred.txt)"]
        block+=["~","~+","~-","~root","a:~","$'fake\\x41'"]
        keep={"glob":("fake-f*","fake-f*"),"brace":("{fake-a,fake-b}","{fake-a,fake-b}"),
              "single-quoted dollar":("'fake$_literal'","fake$_literal"),
              "single-quoted tilde":("'~'","~"),
              "single-quoted shell state":("'$PWD $RANDOM $(x)'","$PWD $RANDOM $(x)")}
        for form in block:
            with self.subTest(form=form,strict=True):
                with self.assertRaises(ValueError,msg=form):
                    scrubber.parse_env("FAKE_TOKEN="+form+"\n",strict=True)
            with self.subTest(form=form,strict=False):
                self.assertTrue(scrubber.parse_env("FAKE_TOKEN="+form+"\n"),form)
        for label,(raw,value) in keep.items():
            with self.subTest(keep=label):
                self.assertIn(value,scrubber.parse_env("FAKE_TOKEN="+raw+"\n",strict=True))
        with self.subTest(keep="reference to an earlier variable in the same file"):
            self.assertIn("fake-base-value",scrubber.parse_env("FAKE_BASE=fake-base-value\nFAKE_TOKEN=$FAKE_BASE\n",strict=True))
            self.assertIn("fake-base-value",scrubber.parse_env("FAKE_BASE=fake-base-value\nFAKE_TOKEN=${FAKE_BASE}\n",strict=True))
        # End to end: a sourcing command exits 2 and nothing after the source runs.
        script=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        stale=dict(os.environ); stale["_"]="/usr/bin/fake-stale-last-arg"
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,"fake-cred.txt").write_text("FAKE-CREDENTIAL-CONTENTS\n")
            for form in block:
                Path(directory,"fake-sourced.env").write_text("FAKE_TOKEN="+form+"\n")
                proc=subprocess.run(["/usr/bin/python3",str(script),"--",
                                     "set +o posix; : fake-runtime-secret-0123; . ./fake-sourced.env; echo \"$FAKE_TOKEN\"; echo after"],
                                    cwd=directory,capture_output=True,env=stale)
                self.assertEqual(proc.returncode,2,form)
                self.assertNotIn(b"fake-runtime-secret",proc.stdout+proc.stderr,form)
                self.assertNotIn(b"FAKE-CREDENTIAL-CONTENTS",proc.stdout+proc.stderr,form)
                self.assertNotIn(b"after",proc.stdout,form)

    def test_env_parser_masks_expanded_unbraced_references_in_every_shape(self):
        scrubber=self._load_scrubber("scrubber_unbraced")
        scrubber.os.environ["FAKE_REF_SOURCE"]="fake-referenced-value-42"
        try:
            for text in ("FAKE_A=$FAKE_REF_SOURCE\n",
                         "FAKE_B=fake words $FAKE_REF_SOURCE\n",
                         "FAKE_C=\"fake open $FAKE_REF_SOURCE\nfake line two\"\n",
                         "FAKE_D=\"fake open\n$FAKE_REF_SOURCE tail\"\n"):
                for strict in (False,True):
                    self.assertIn("fake-referenced-value-42",scrubber.parse_env(text,strict=strict),
                                  "expanded unbraced reference not masked: "+repr(text))
        finally:
            del scrubber.os.environ["FAKE_REF_SOURCE"]

    def test_sourced_unbraced_reference_is_masked_after_expansion(self):
        scrubber=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        fake="fake-source-value-0123456789"
        with tempfile.TemporaryDirectory(prefix="secrets-guard-unbraced-") as temp:
            env_file=Path(temp)/"fake.env"
            env_file.write_text("FAKE_TOKEN=$FAKE_SOURCE\n")
            command=("set -a; . "+shlex.quote(str(env_file))+"; set +a; python3 -c "+
                     shlex.quote("import os; print(os.environ['FAKE_TOKEN'])"))
            env=dict(FAKE_ENV_BASE,HOME=temp,TMPDIR=temp,FAKE_SOURCE=fake)
            result=subprocess.run([sys.executable,str(scrubber),"--",command],cwd=temp,capture_output=True,env=env)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors="replace"))
        self.assertNotIn(fake.encode(),result.stdout+result.stderr)
        self.assertEqual(result.stdout,b"[MASKED]\n")

    def test_sourced_reference_to_shell_local_variable_fails_closed(self):
        scrubber=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        fake="fake-shell-local-0123456789"
        with tempfile.TemporaryDirectory(prefix="secrets-guard-local-") as temp:
            env_file=Path(temp)/"fake.env"
            env_file.write_text("FAKE_TOKEN=$FAKE_LOCAL\nFAKE_OTHER=${FAKE_UNSET_ANYWHERE:-fake-default}\n")
            app=shlex.quote("import os; print(os.environ['FAKE_TOKEN'])")
            env=dict(FAKE_ENV_BASE,HOME=temp,TMPDIR=temp)
            local=("FAKE_LOCAL="+fake+"; set -a; . "+shlex.quote(str(env_file))+"; set +a; python3 -c "+app)
            result=subprocess.run([sys.executable,str(scrubber),"--",local],cwd=temp,capture_output=True,env=env)
            self.assertNotIn(fake.encode(),result.stdout+result.stderr,"shell-local value leaked")
            self.assertEqual(result.returncode,2); self.assertIn(b"command not run",result.stderr)
            # The same when the name is already exported and the command overwrites it.
            exported=dict(env,FAKE_LOCAL="fake-stale-exported-0123")
            result=subprocess.run([sys.executable,str(scrubber),"--",local],cwd=temp,capture_output=True,env=exported)
            self.assertNotIn(fake.encode(),result.stdout+result.stderr,"overwritten exported value leaked")
            self.assertEqual(result.returncode,2); self.assertIn(b"command not run",result.stderr)
            # A run-time reference inside a ${NAME:-...} default is checked the same way.
            nested=Path(temp)/"fake-nested.env"
            nested.write_text("FAKE_TOKEN=${FAKE_UNSET_ANYWHERE:-$FAKE_LOCAL}\n")
            nested_cmd=("FAKE_LOCAL="+fake+"; set -a; . "+shlex.quote(str(nested))+"; set +a; python3 -c "+app+"; echo after")
            result=subprocess.run([sys.executable,str(scrubber),"--",nested_cmd],cwd=temp,capture_output=True,env=env)
            self.assertNotIn(fake.encode(),result.stdout+result.stderr,"nested default value leaked")
            self.assertEqual(result.returncode,2); self.assertIn(b"command not run",result.stderr)
            self.assertNotIn(b"after",result.stdout)
            # A PATH the command sets before sourcing can make any word after a spaced value a command.
            bindir=Path(temp)/"fakebin"; bindir.mkdir()
            (Path(temp)/"fake-path-cred.txt").write_text("fake-path-secret-0123456789\n")
            (bindir/"fakeleak").write_text("#!/bin/sh\n/bin/cat "+shlex.quote(str(Path(temp)/"fake-path-cred.txt"))+"\n"); (bindir/"fakeleak").chmod(0o755)
            spaced=Path(temp)/"fake-spaced.env"; spaced.write_text("FAKE_X=a fakeleak file\n")
            path_cmd=("PATH="+shlex.quote(str(bindir))+":/usr/bin:/bin; . "+shlex.quote(str(spaced))+"; echo after")
            result=subprocess.run([sys.executable,str(scrubber),"--",path_cmd],cwd=temp,capture_output=True,env=env)
            self.assertNotIn(b"fake-path-secret",result.stdout+result.stderr,"runtime-PATH command ran")
            self.assertEqual(result.returncode,2); self.assertIn(b"command not run",result.stderr)
            self.assertNotIn(b"after",result.stdout)
            # A name the file itself set earlier is known, even when the command mentions it.
            parser=self._load_scrubber("scrubber_assigned_first")
            self.assertIn("fake-path-spaced-0123",parser.parse_env("FAKE_X=fake-path-spaced-0123 Name\n",strict=True))
            with self.assertRaises(ValueError):
                parser.parse_env("FAKE_X=a fakeleak file\n",strict=True,local_names={"PATH"})
            for value in ("${FAKE_UNSET_ANYWHERE:-$FAKE_LOCAL}","${FAKE_UNSET_ANYWHERE-x$FAKE_LOCAL}"):
                with self.assertRaises(ValueError,msg=value):
                    parser.parse_env("FAKE_TOKEN="+value+"\n",strict=True,local_names={"FAKE_LOCAL"})
            with self.assertRaises(ValueError):
                parser.parse_env("FAKE_TOKEN=${FAKE_UNSET_ANYWHERE:-$1}\n",strict=True)
            self.assertIn("fake-nested-default-0123",parser.parse_env(
                "FAKE_TOKEN=${FAKE_UNSET_ANYWHERE:-fake-nested-default-0123}\n",strict=True))
            self.assertIn("fake-assigned-first-0123",parser.parse_env(
                "FAKE_LOCAL=fake-assigned-first-0123\nFAKE_TOKEN=$FAKE_LOCAL\n",strict=True,local_names={"FAKE_LOCAL"}))
            # A reference to a name set nowhere expands to empty, as in the shell, and still runs.
            plain=("set -a; . "+shlex.quote(str(env_file))+"; set +a; echo ok")
            result=subprocess.run([sys.executable,str(scrubber),"--",plain],cwd=temp,capture_output=True,env=env)
            self.assertEqual((result.returncode,result.stdout),(0,b"ok\n"),result.stderr.decode(errors="replace"))
            # A name assigned in another env file the command may load also fails closed.
            (Path(temp)/".env.local").write_text("FAKE_LOCAL="+fake+"\n")
            result=subprocess.run([sys.executable,str(scrubber),"--",plain],cwd=temp,capture_output=True,env=env)
            self.assertEqual(result.returncode,2)

    def test_cwd_dotenv_example_with_spaced_value_never_blocks_command(self):
        scrubber=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        with tempfile.TemporaryDirectory(prefix="secrets-guard-example-") as temp:
            for name in (".env.example",".env.sample",".env.template"):
                (Path(temp)/name).write_text("EMAIL_FROM=Fake Sender <fake-sender@example.invalid>\nFAKE_DYN=$(echo fake)\n")
            subprocess.run(["git","init","-q",temp],check=True)
            env=dict(FAKE_ENV_BASE,HOME=temp,TMPDIR=temp)
            for command in ("echo ok","git status --short","cat .env.example"):
                result=subprocess.run([sys.executable,str(scrubber),"--",command],cwd=temp,capture_output=True,env=env)
                self.assertEqual(result.returncode,0,command+" blocked: "+result.stderr.decode(errors="replace"))
                self.assertNotIn(b"fake-sender@example.invalid",result.stdout+result.stderr,"example value not masked")
            self.assertEqual(subprocess.run([sys.executable,str(scrubber),"--","echo ok"],cwd=temp,capture_output=True,env=env).stdout,b"ok\n")

    def test_sourced_unquoted_spaced_value_runs_and_is_masked(self):
        scrubber=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        fake="fake-live-value-0123456789"
        with tempfile.TemporaryDirectory(prefix="secrets-guard-spaced-") as temp:
            env_file=Path(temp)/"fake.env"
            env_file.write_text("FAKE_X="+fake+"\r\nFAKE_NAME=Fake Spaced fake-spaced-word\r\n# fake comment\r\nexport FAKE_Y=fake-exported-0123456789\r\n")
            command=("set -a; . "+shlex.quote(str(env_file))+"; set +a; python3 -c "+
                     shlex.quote("import os; print(os.environ['FAKE_X']); print(os.environ['FAKE_Y'])"))
            env=dict(FAKE_ENV_BASE,HOME=temp,TMPDIR=temp)
            result=subprocess.run([sys.executable,str(scrubber),"--",command],cwd=temp,capture_output=True,env=env)
        combined=result.stdout+result.stderr
        self.assertNotIn(b"failed closed",combined); self.assertNotIn(b"command not run",combined)
        self.assertNotIn(fake.encode(),combined); self.assertNotIn(b"fake-exported-0123456789",combined)
        self.assertEqual(result.stdout.replace(b"\r",b""),b"[MASKED]\n[MASKED]\n")


if __name__ == "__main__":
    unittest.main()
