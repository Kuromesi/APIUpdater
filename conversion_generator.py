import yaml, os, re
from code_generator import CodeGenerator


class ConversionGenerator():
    def __init__(self, project_path) -> None:
        self.project_path = project_path
        self.crds = None
        self.get_crds()
        os.chdir(project_path)
    
    def get_crds(self):
        project_file = os.path.join(self.project_path, "PROJECT")
        with open(project_file, 'r') as f:
            project_yaml = yaml.safe_load(f)
        crds = {}
        for crd in project_yaml['resources']:
            if crd['version'] == "v1alpha1":
                crds[crd['kind']] = {"group": crd['group']}
            # elif crd['version'] == "v1beta1":
            #     del crds[crd['kind']]
        self.crds = crds
    
    def create_api(self):
        crds = self.crds
        for k, v in crds.items():
            command = f"echo n | kubebuilder create api --group {v['group']} --version v1beta1 --kind {k} --namespaced=true --resource"
            os.system(command)
        for k, v in crds.items():
            old_version = os.path.join(self.project_path, f"apis/{v['group']}/v1alpha1/{k.lower()}_types.go")
            with open(old_version, 'r') as f:
                old = f.read().replace("package v1alpha1", "package v1beta1")
            new_version = os.path.join(self.project_path, f"apis/{v['group']}/v1beta1/{k.lower()}_types.go")
            with open(new_version, 'w') as f:
                f.write(old)

    def create_conversion_function(self):
        old_version = "v1alpha1"
        new_version = "v1beta1"
        paths = [f"/Users/kuromesi/MyCOde/kind/share/kuromesi.com/kruise/apis/apps/{old_version}",
                 f"/Users/kuromesi/MyCOde/kind/share/kuromesi.com/kruise/apis/policy/{old_version}"]
        cg = CodeGenerator(paths)
        crds = self.crds
        cg.scan_code()
        for k, v in crds.items():
            if k == "StatefulSet":
                continue
            conversion = os.path.join(self.project_path, f"apis/{v['group']}/{new_version}/{k.lower()}_conversion.go")
            with open(conversion, 'w') as f:
                content = f'''/*
Copyright 2020 The Kruise Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package {new_version}

func (*{k}) Hub() {{}}'''
                f.write(content)
            os.system(f"go fmt {coversion}")
            conversion = os.path.join(self.project_path, f"apis/{v['group']}/{old_version}/{k.lower()}_conversion.go")
            os.system(f"go fmt {conversion}")
            with open(conversion, 'w') as f:
                header = f'''/*
Copyright 2020 The Kruise Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package {old_version}

import (
    "fmt"

    "github.com/openkruise/kruise/apis/{v['group']}/{new_version}"
    "sigs.k8s.io/controller-runtime/pkg/conversion"
)'''
                content = [header]
                content.append(f"func (src *{k}) ConvertTo(dstRaw conversion.Hub) error " + "{")
                content.append("switch t := dstRaw.(type) {")
                content.append(f"case *v1beta1.{k}:")
                content.append(f"dst := dstRaw.(*v1beta1.{k})")
                lines = cg.deep_gen(cg.objects, k, "dst", "", "src", "", "v1beta1")
                content.extend(lines)
                content.append("default:\nreturn fmt.Errorf(\"unsupported type %v\", t)\n}\nreturn nil\n}\n")
                content.append(f"func (dst *{k}) ConvertFrom(srcRaw conversion.Hub) error " + "{")
                content.append("switch t := srcRaw.(type) {")
                content.append(f"case *v1beta1.{k}:")
                content.append(f"src := srcRaw.(*v1beta1.{k})")
                lines = cg.deep_gen(cg.objects, k, "dst", "", "src", "", "")
                content.extend(lines)
                content.append("default:\nreturn fmt.Errorf(\"unsupported type %v\", t)\n}\nreturn nil\n}\n")
                f.writelines(line + '\n' for line in content)
            os.system(f"go fmt {conversion}")
    
    def update_dependencies(self):
        file_list = self.get_all_files("/Users/kuromesi/MyCOde/kind/share/kuromesi.com/kruise/test")
        is_kruise = re.compile(r"github.com/openkruise/.*/v1alpha1")
        for file in file_list:
            with open(file, 'r') as f:
                lines = f.readlines()
            new_lines = []
            contains = False
            in_import = False
            # check import
            patterns = []
            prefixes = []
            for line in lines:
                if "import (" in line or in_import:
                    if not in_import:
                        in_import = True
                    elif ")" in line:
                        in_import = False
                        if not contains:
                            new_lines = lines
                            break
                    elif is_kruise.findall(line):
                        tmp = line.strip()
                        prefix = tmp.split()
                        if len(prefix) > 1:
                            prefix = prefix[0]
                        else: 
                            prefix = "v1alpha1"
                        line = line.replace("v1alpha1", "v1beta1")
                        new_prefix = prefix.replace("v1alpha1", "v1beta1")
                        prefixes.append(new_prefix)
                        patterns.append(f"(?<![a-zA-Z]){prefix}(?![a-zA-Z])")
                        contains = True
                elif contains and "apps.kruise.io/v1beta1" not in line:
                    line = line.replace("AppsV1alpha1()", "AppsV1beta1()")
                    line = line.replace("PolicyV1alpha1()", "PolicyV1beta1()")
                    for pattern in patterns:
                        line = re.sub(pattern, prefixes[patterns.index(pattern)], line)
                new_lines.append(line)
            with open(file, 'w') as f:
                f.writelines(new_lines)
            os.system(f"go fmt {file}")

    def change_kubebuilder_anno(self):
        files = self.get_all_files("/Users/kuromesi/MyCOde/kind/share/kuromesi.com/kruise/pkg/webhook")
        for file in files:
            if not re.findall(r"webhooks?.go", file):
                continue
            with open(file, "r") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                line = line.replace("versions=v1alpha1", "versions=v1alpha1;v1beta1")
                line = line.replace("-v1alpha1", "")
                new_lines.append(line)
            with open(file, "w") as f:
                f.writelines(new_lines)

    def get_all_files(self, directory):
        file_list = []
        for root, directories, files in os.walk(directory):
            if "client" in root[len(directory) - 1: ]:
                continue
            for file in files:
                if ".go" in file:
                    file_path = os.path.join(root, file)
                    file_list.append(file_path)
        return file_list
        
if __name__ == "__main__":
    cg = ConversionGenerator("/Users/kuromesi/MyCOde/kind/share/kuromesi.com/kruise")
    cg.change_kubebuilder_anno()
    # cg.update_dependencies()
    # cg.create_api()
    # cg.create_conversion_function()
    # cg.get_crds()
    # crds = cg.crds
    # cg = CodeGenerator("/Users/kuromesi/MyCOde/kind/share/kuromesi.com/kruise/apis/apps/v1alpha1")
    # cg.scan_code(crds)
    