"""
Script to build out the python package opendp.whitenoise.core in 3 steps
(a) Build the whitenoise-core Rust validator and runtime
(b) Create the Python classes from Protobuf definitions
(c) Build the python components.py and variant_message_map.py file
"""
import json
import os
import re
from datetime import datetime
import subprocess
import shutil

# decrease compiler optimization for faster builds
WN_DEBUG = os.environ.get("WN_DEBUG", "false") != "false"
# get the environment variable to use precompiled external libraries
WN_USE_SYSTEM_LIBS = os.environ.get("WN_USE_SYSTEM_LIBS", "false") != "false"
# get the environment variable to disable gmp/mpfr noise
WN_USE_VULNERABLE_NOISE = os.environ.get("WN_USE_VULNERABLE_NOISE", "false") != "false"

# turn on backtraces in rust (for build.rs)
os.environ['RUST_BACKTRACE'] = 'full'  # '1'
os.environ['RUSTFLAGS'] = ""

# protoc must be installed and on path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
package_dir = os.path.join(root_dir, 'opendp', 'whitenoise', 'core')
rust_dir = os.path.join(root_dir, 'whitenoise-core')
prototypes_dir = os.path.join(rust_dir, "validator-rust", "prototypes")
lib_dir = os.path.join(package_dir, "lib")

if not os.path.exists(rust_dir):
    # when the repository is cloned, the --recurse-submodules inits and updates the core submodule
    # if this argument is not passed, you can still init and update the core submodule
    raise Exception(
        "whitenoise-core submodule is not initiated. "
        "Read the setup instructions, then run `git submodule init`, `git submodule update`.")


def build_rust_binaries():
    """(a) Build the Rust Validator and Runtime"""
    print(build_rust_binaries.__doc__)

    rust_build_path = os.path.join(rust_dir, 'target', 'debug' if WN_DEBUG else 'release')
    rust_build_cmd = 'cargo build' if WN_DEBUG else 'cargo +stable build --release'

    toml_path = os.path.join(rust_dir, "ffi-rust", "Cargo.toml")

    cargo_features = ' --features use-direct-api'
    if WN_USE_VULNERABLE_NOISE:
        cargo_features = ' --no-default-features --features "use-runtime use-direct-api"'
    elif WN_USE_SYSTEM_LIBS:
        cargo_features = ' --features "use-system-libs use-direct-api"'

    rust_build_cmd = f"{rust_build_cmd}{cargo_features} --manifest-path={toml_path}"

    # build shared library
    subprocess.call(rust_build_cmd, shell=True)

    shutil.rmtree(lib_dir, ignore_errors=True)
    os.makedirs(lib_dir, exist_ok=True)

    for filename in os.listdir(rust_build_path):
        if filename.startswith("libwhitenoise_ffi"):
            shutil.copy(os.path.join(rust_build_path, filename), lib_dir)


def build_python_protobufs():
    """(b) Build the Python classes from Protobuf definitions"""
    print(build_python_protobufs.__doc__)

    subprocess.call(f"protoc --python_out={package_dir} *.proto", shell=True, cwd=prototypes_dir)

    for proto_name in os.listdir(package_dir):
        if not proto_name.endswith("_pb2.py"):
            continue

        proto_path = os.path.join(package_dir, proto_name)
        with open(proto_path, 'r') as proto_file:
            proto_text = "".join(
                ["from . " + line if re.match("^import.*_pb2.*", line) else line for line in proto_file.readlines()])

        with open(proto_path, 'w') as proto_file:
            proto_file.write(proto_text)


def build_python_components():
    """(c) Build the python components.py and variant_message_map.py files"""
    print(build_python_components.__doc__)

    components_dir = os.path.join(prototypes_dir, "components")

    generated_code_header = '''"""
Warning, this file is autogenerated by code_generation.py.
Don't modify this file manually. (Generated: %s)
"""
''' % datetime.now()

    generated_code = """%s
from .base import Component
from .value import serialize_privacy_usage

""" % generated_code_header

    # This links the variant in the Component proto to the corresponding message
    variant_message_map = {}

    for file_name in sorted(os.listdir(components_dir)):
        if not file_name.endswith(".json"):
            continue

        component_path = os.path.join(components_dir, file_name)
        with open(component_path, 'r') as component_schema_file:

            try:
                component_schema = json.load(component_schema_file)
            except Exception as err:
                print("MALFORMED JSON FILE: ", file_name)
                raise err

        def standardize_argument(name):
            argument_schema = component_schema['arguments'][name]
            if argument_schema.get('type_value') == 'Jagged':
                name += ', value_format="jagged"'
            return name

        def standardize_option(name):
            option_schema = component_schema['options'][name]
            if option_schema.get('type_proto') == 'repeated PrivacyUsage':
                return f'serialize_privacy_usage({name})'
            return name

        def document_argument(prefix, name, arg):
            return f'{prefix}{name}: {arg.get("description", "")}'

        docstring = f"{component_schema['id']} Component\n"
        if 'description' in component_schema:
            docstring += "\n" + component_schema['description'] + "\n"

        if component_schema.get('any_argument'):
            docstring += "\n:param arguments: dictionary of arguments to supply to the function"

        for argument in component_schema['arguments']:
            docstring += "\n" + document_argument(":param ", argument, component_schema['arguments'][argument])

        for option in component_schema['options']:
            docstring += "\n" + document_argument(":param ", option, component_schema['options'][option])

        if not component_schema.get('any_argument'):
            docstring += "\n:param kwargs: data bounds of the form [argument]_[bound]=[lower | upper | categories | ...]"

        docstring += "\n" + document_argument(":return", "", component_schema['return'])

        docstring = '\n'.join(["    " + line for line in docstring.split("\n")])

        variant_message_map[component_schema['id']] = component_schema['name']

        # sort arguments with defaults to the end of the signature
        default_arguments = {
            True: [],
            False: []
        }

        if component_schema.get('any_argument'):
            default_arguments[False].append('arguments')

        # add default value to arguments
        for arg in list(dict.fromkeys([
            *component_schema['arguments'].keys(),
            *component_schema['options'].keys()])):

            metadata = component_schema['arguments'].get(arg, component_schema['options'].get(arg, {}))

            if 'default_python' in metadata:
                default_arguments[True].append(arg + f'={metadata["default_python"]}')
            else:
                default_arguments[False].append(arg)

        signature_tokens = [*default_arguments[False], *default_arguments[True]]

        if not component_schema.get('any_argument'):
            signature_tokens.append('**kwargs')

        # create the function signature
        signature_string = ", ".join(signature_tokens)

        # create the arguments to the Component constructor
        component_arguments = "{\n            " \
                              + ",\n            ".join([f"'{name}': Component.of({standardize_argument(name)})"
                                                        for name in component_schema['arguments']]) \
                              + "\n        }"
        component_options = "{\n            " \
                            + ",\n            ".join([f"'{name}': {standardize_option(name)}"
                                                      for name in component_schema['options']]) \
                            + "\n        }"
        component_constraints = "None"

        # handle components with unknown number of arguments
        if component_schema.get('any_argument'):
            component_arguments = f"arguments"
        else:
            component_constraints = "kwargs"

        # build the call to create a Component with the prior argument strings
        generated_code += f"""
def {component_schema['name']}({signature_string}):
    \"\"\"\n{docstring}
    \"\"\"
    return Component(
        "{component_schema['id']}",
        arguments={component_arguments},
        options={component_options},
        constraints={component_constraints})

"""

    output_path = os.path.join(package_dir, 'components.py')
    with open(output_path, 'w') as generated_file:
        generated_file.write(generated_code)
    print('    - file written: ', output_path)

    variant_message_map_path = os.path.join(package_dir, 'variant_message_map.py')
    with open(variant_message_map_path, 'w') as generated_map_file:
        map_text = f"""{generated_code_header}
variant_message_map = %s""" % (json.dumps(variant_message_map, indent=4))
        generated_map_file.write(map_text)
    print('    - file written: ', variant_message_map_path)


if __name__ == '__main__':
    build_rust_binaries()
    build_python_protobufs()
    build_python_components()
