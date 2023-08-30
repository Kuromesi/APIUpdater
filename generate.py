import yaml, os, re


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
        cg.scan_code(crds)
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
        file_list = self.get_all_files("pkg")
        for file in file_list:
            with open(file, 'r') as f:
                lines = f.readlines()
            new_lines = []
            contains = False
            in_import = False
            # check import
            for line in lines:
                if "import (" in line or in_import:
                    if not in_import:
                        in_import = True
                    elif ")" in line:
                        in_import = False
                    elif "github.com/openkruise/kruise/apis/apps/v1alpha1" in line:
                        tmp = line.strip()
                        prefix = tmp.split()
                        if len(prefix) > 1:
                            prefix = prefix[0]
                        else: 
                            prefix = "v1alpha1"
                        line = line.replace("v1alpha1", "v1beta1")
                        new_prefix = prefix.replace("v1alpha1", "v1beta1")
                        pattern = "(?<![a-zA-Z])%s(?![a-zA-Z])"%prefix
                        contains = True
                elif contains and "apps.kruise.io/v1beta1" not in line and re.findall(pattern, line):
                    line = re.sub(pattern, new_prefix, line)
                new_lines.append(line)
            with open(file, 'w') as f:
                f.writelines(new_lines)
            os.system(f"go fmt {file}")

    def get_all_files(self, directory):
        file_list = []
        for root, directories, files in os.walk(directory):
            for file in files:
                if ".go" in file:
                    file_path = os.path.join(root, file)
                    file_list.append(file_path)
        return file_list
        

class CodeGenerator():
    def __init__(self, src_path) -> None:
        self.src_path = src_path
        self.excluded = ["doc.go", "openapi_generated.go", "zz_generated.deepcopy.go"]
        self.type_struct_re = re.compile(r"type (.*) struct")
    
    def scan_code(self, crds):
        objects = {}
        type_def = {}
        for path in self.src_path:
            for file in os.listdir(path):
                if file in self.excluded or "_conversion" in file:
                    continue
                file = os.path.join(path, file)
                with open(file, 'r') as f:
                    file = f.readlines()
                # preproc
                file = self.remove_comment(file)

                for p in range(len(file)):
                    line = file[p]
                    if self.type_struct_re.findall(line):
                        obj_name = self.type_struct_re.findall(line)[0]
                        fields, p = self.get_struct(file, p)
                        objects[obj_name] = fields
                    elif line[: 4] == "type":
                        line = line.split()
                        assert len(line) == 3
                        type_def[line[1]] = line[2]
        self.objects = objects
        self.type_def = type_def
        self.check_dfs()

    def check_dfs(self):
        objects = self.objects
        type_def = self.type_def
        map_pattern = re.compile(r"map\[(.*)\](.*)")
        for k, v in objects.items():
            for k1, v1 in v.items():
                v_type = v1['type'].replace("[]", "").replace("*", "")
                v1["need_dfs"] = False
                v1["is_type_def"] = False
                v1['is_map'] = False
                if v_type in objects:
                    v1["need_dfs"] = True
                elif v_type in type_def:
                    tmp = type_def[v_type].replace("[]", "").replace("*", "")
                    if tmp in objects:
                        v[k1]['type'] = type_def[v_type]
                        if "[]" in type_def[v_type]:
                            v1["is_list"] = True
                        if "*" in type_def[v_type]:
                            v1['is_ptr'] = True
                        v1["need_dfs"] = True
                    else:
                        v1["is_type_def"] = True
                elif map_pattern.findall(v_type):
                    v1['is_map'] = True
                    assert map_pattern.findall(v_type)[0][0] not in objects
                    if map_pattern.findall(v_type)[0][1] in objects:
                        v1["need_dfs"] = True

    
    def deep_gen(self, objects, name, dst, dst_field, src, src_field, version):
        lines = []
        fields = objects[name.replace("*", "").replace("[]", "")]
        for k, v in fields.items():
            if k == "TypeMeta":
                continue
            if v['is_list'] and v['need_dfs']:
                array = k
                array = array[0].lower() + array[1: ]
                v_type = v['type'].replace("[]", "").replace("*", "")
                for_val = "%s_val"%array
                for_idx = "%s_idx"%array
                if src_field:
                    in_val = f"{src}.{src_field}.{k}".strip(".")
                else:
                    in_val = f"{src}.{k}".strip(".")
                type_prefix = f"{version}.{v_type}".strip(".")
                array_def = f"{array} := make([]{type_prefix}, len({in_val}))"
                for_start = f"for {for_idx}, {for_val} := range {in_val} " + "{"
                lines.append(array_def)
                lines.append(for_start)
                tmp = self.deep_gen(objects, v['type'], f"{array}[{for_idx}]", "", for_val, "", version)
                lines.extend(tmp)
                lines.append("}")
                if dst_field:
                    assign_val = f"{dst}.{dst_field}.{k}".strip(".")
                else:
                    assign_val = f"{dst}.{k}".strip(".")
                lines.append(f"{assign_val} = {array}")
            elif v['is_map'] and v['need_dfs']:
                obj_map = k
                obj_map = obj_map[0].lower() + obj_map[1: ]
                for_val = "%s_val"%obj_map
                for_key = "%s_key"%obj_map
                if src_field:
                    in_val = f"{src}.{src_field}.{k}".strip(".")
                else:
                    in_val = f"{src}.{k}".strip(".")
                assign = re.findall(r"map\[.*\](.*)", v['type'])[0]
                map_type = f"{version}.{assign}".strip(".")
                map_type = v['type'].replace(assign, map_type)
                map_def = f"{obj_map} := make({map_type}, len({in_val}))"
                for_start = f"for {for_key}, {for_val} := range {in_val} " + "{"
                
                assign_val = assign
                assign = assign[0].lower() + assign[1: ]
                assign_val = f"{version}.{assign_val}".strip(".")
                assign_line = f"{assign} := {assign_val}{{}}"
                lines.append(map_def)
                lines.append(for_start)
                lines.append(assign_line)
                tmp = self.deep_gen(objects, re.findall(r"map\[.*\](.*)", v['type'])[0], assign, "", for_val, "", version)
                lines.extend(tmp)
                lines.append(f"{obj_map}[{for_key}] = {assign}")
                lines.append("}")
                assign = f"{dst}.{dst_field}.{k}".replace("..", ".")
                lines.append(f"{assign} = {obj_map}")
            elif v['need_dfs']:                    
                tmp = self.deep_gen(objects, v['type'], dst, f"{dst_field}.{k}".strip("."), src, f"{src_field}.{k}".strip("."), version)
                if v['is_ptr']:
                    cur_src_field = f"{src_field}.{k}".strip(".")
                    lines.append(f"if {src}.{cur_src_field} != nil " + "{")

                    assign = f"{dst_field}.{k}".strip(".")
                    assign_val = f"{version}.{v['type'].replace('*', '')}{{}}".strip(".")
                    assign = f"{dst}.{assign} = &{assign_val}"
                    lines.append(assign)
                    lines.extend(tmp)
                    lines.append("}")
                else:
                    lines.extend(tmp)
            else:
                cur_dst_field = f"{dst_field}.{k}".strip(".")
                cur_src_field = f"{src_field}.{k}".strip(".")
                if v['is_type_def']:
                    v_type = v['type'].replace("[]", "").replace("*", "")
                    type_prefix = f"{version}.{v_type}".strip(".")
                    line = f"{dst}.{cur_dst_field} = {type_prefix}({src}.{cur_src_field})"
                else:
                    line = f"{dst}.{cur_dst_field} = {src}.{cur_src_field}"
                lines.append(line)
        return lines
    
    def remove_comment(self, file):
        tmp = []
        comment = False
        for line in file:
            if "/*" in line:
                comment = True
                continue
            if "*/" in line:
                comment = False
                continue
            if "//" in line:
                continue
            if comment:
                continue
            if not line.strip():
                continue
            tmp.append(line)
        return tmp

    def get_struct(self, file, p):
        fields = {}
        p += 1
        pattern = r'`[^`]*`'
        for i in range(p, len(file)):
            line = file[i]
            if line.strip() == "}":
                return fields, i
            line = re.sub(pattern, "", line).strip()
            field = line.split()
            if len(field) == 2:
                field_name, field_type = field
            elif len(field) == 1:
                field_type = field[0]
                field_name = field_type.split(".")[-1]
            else:
                raise Exception("unexpected input: %s"%line)
            need_dfs = True
            is_list = False
            is_ptr = False
            # if "." in field_type:
            #     need_dfs = False
            if "[]" in field_type:
                is_list = True
            if "*" in field_type:
                is_ptr = True
            fields[field_name] = {"type": field_type, "is_list": is_list, "is_ptr": is_ptr}




if __name__ == "__main__":
    cg = ConversionGenerator("/Users/kuromesi/MyCOde/kind/share/kuromesi.com/kruise")
    # cg.update_dependencies()
    # cg.create_api()
    cg.create_conversion_function()
    # cg.get_crds()
    # crds = cg.crds
    # cg = CodeGenerator("/Users/kuromesi/MyCOde/kind/share/kuromesi.com/kruise/apis/apps/v1alpha1")
    # cg.scan_code(crds)
    
    