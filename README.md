# MIXIN

See also [MIXIN Language Specification](specification.md).

## 简介

**MIXIN**（Multi-language Interoperable eXtensible Interface Notion）是一种基于 YAML、JSON 和 TOML 的编程语言，旨在通过 mixin 的组合和配置来表达所有逻辑和数据结构。MIXIN 支持多语言互操作性，允许在不同平台上高效执行计算图。目前，MIXIN 主要通过 Nix 实现其运行时和 JIT 编译器，将 MIXIN 编译为 Nix 表达式。

## 基本概念

### mixin

- **定义**：mixin 是 MIXIN 语言中的复用单元，用于统一所有类型的表示。
- **功能**：mixin 可以像值一样操作、像类一样继承、像函数一样使用。
- **组成**：所有逻辑和数据结构通过 mixin 的组合和配置表示。

### 特殊的 mixin

- **继承**：表示为字符串数组，用于继承其他 mixin 或模块。相当于 Haskell 里的 thunk，只有在需要的时候才会被求值。
- **属性**：mixin 的属性定义集合，可以包含其他 mixin。

## 术语定义

### 继承

- **定义**：一个 mixin 继承，表示为字符串数组。
- **使用方法**：可以用于指向其他模块或 mixin。

### 属性

- **定义**：属性定义的集合，可以包括其他 mixin。
- **使用方法**：用于定义 mixin 的内部结构或行为。

### 继承和属性

- **定义**：一个表示继承和属性或嵌套结构组合的数组。
- **使用方法**：用于 mixin 之间的继承关系或属性嵌套。

## 语法与文件格式

### 源码表示形式

MIXIN 支持以下文件格式的源码表示：

- **YAML**：扩展名为 `.mixin.yaml`
- **JSON**：扩展名为 `.mixin.json`
- **TOML**：扩展名为 `.mixin.toml`

**注意**：MIXIN 只使用 YAML、JSON 和 TOML 中可序列化为 JSON 的子集，不支持 YAML 的 anchor、alias、tags 等特性。

## 命名规范

### 文件名

- **格式**：小写字母，单词之间使用下划线分隔，且文件名必须包含 `.mixin.` 以指明其为 MIXIN 文件。
- **说明**：如果定义一个主要概念，文件名应该用单数名词；如果其中包含若干个实例，文件名应该用复数名词。
- **示例**：`builtins.mixin.yaml`、`list.mixin.yaml`、`utilities.mixin.yaml`

### 命名空间、值或函数使用的 mixin

- **格式**：小写字母，单词之间使用下划线分隔。
- **限制**：命名空间、值或函数的 mixin 不应该被其他 mixin 多重继承。
- **函数优先**：函数应该优先采用自由函数而不是方法，因为 MIXIN 语法不支持链式调用语法，即，不支持类似 `a.f(b).g(c).h(d)` 的连续调用写法。
- **示例**：`addend1`、`operand2`、`multiplicand`、`add`、`pow`

### 类型使用的 mixin

- **格式**：大写驼峰命名。
- **说明**：类型可以被其他 mixin 多重继承。
- **示例**：`Number`、`Boolean`、`Tuple`

### 静态值使用的 mixin

- **格式**：大写字母，单词之间使用下划线分隔。
- **说明**：静态值通常是大写驼峰命名的类型 mixin 中的成员，而不是小写字母下划线定义的 mixin 的成员。作为惯例，静态值不应该访问 `this` 属性。
- **示例**：`[Tuple, EMPTY]`

### 顶级目录

- **格式**：小写字母，单词之间使用下划线分隔。
- **说明**：顶级目录用于组织源码、测试和示例代码。它们通常不会被其他 mixin 多重继承，唯一的例外是在编译和解释时会混入编译器和解释器。
- **示例**：`src`、`tests`、`examples`

## 模块化与文件组织

### 跨文件继承

- **继承格式**：使用文件路径作为继承前缀，路径的每个部分之间用逗号 `,` 分隔。例如：`[path, to, other_file, mixin_name, sub_mixin]`。
- **继承解析规则**：
  - 继承的格式能继承 `./path/to/other_file.mixin.yaml` 文件里的 `mixin_name` 属性中的 `sub_mixin` 属性。
  - 如果 `./path` 和 `./path.mixins.*.*` 都不存在，那么会寻找 `../path` 和 `../path.mixins.*`，以此类推，直到源码的根目录。
- **示例**：

  假设有以下目录结构：

  ```
  project/
  ├── path/
  │   └── to/
  │       └── other_file.mixin.yaml
  └── main.mixin.yaml
  ```

  `main.mixin.yaml` 中继承了 `other_file.mixin.yaml`：

  ```yaml
  example_inheritance:
    - [path, to, other_file, mixin_name, sub_mixin]
  ```

  在这种情况下，编译器将首先尝试解析 `./path/to/other_file.mixin.yaml` 中的 `mixin_name` 和 `sub_mixin`。如果找不到相应文件或属性，它将逐级向上查找，直到到达源码的根目录。

  如果有多个源文件可以定义同一个 mixin，编译器将合并这些定义。比如，如果存在以下 2 个文件：

  ```yaml
  # foo.mixin.yaml
  - [SuperMixin0]
  - property1:
      property2: value3
  ```

  ```yaml
  # foo/baz.mixin.yaml
  property1:
    property4: value5
  property6: value7
  ```

  编译器将合并这些定义，等价于把定义放在单个文件 `foo.mixin.yaml` 中：

  ```yaml
  # Merged foo.mixin.yaml
  - [SuperMixin0]
  - property1:
      property2: value3
      property4: value5
    property6: value7
  ```

### 嵌套词法域与省略前缀

- **嵌套词法域**：
  - 允许在同一文件或嵌套词法域中定义多个层级，内层可以继承外层的上下文。

- **省略前缀**：
  - 在同一词法域内，多个继承共享相同的前缀时，可以省略共同的部分，编译器根据上下文自动推断。

- **示例**：

  ```yaml
  math_operations:
    basic:
      Add:
        - [Number]
        - addend1: [Number]
          addend2: [Number]
      Multiply:
        - [Number]
        - multiplicand: [Number]
          multiplier: [Number]

    advanced:
      Square:
        - [basic, Multiply]
        - multiplicand: [Number]
          multiplier: [multiplicand]
  ```

  在 `advanced.Square` 中，继承 `Multiply` 时省略了前缀 `math_operations, basic`。

  继承的第一段只能在词法域中寻找符号，而不能在别的被继承的 mixin 中寻找。例如：

  ````yaml
  foo:
    bar:
    baz:
      - [Qux]
      - x: [foo, bar]
    Qux:
      foo:
        bar: {}
  ````

  `x` 继承了文件根定义的 `[foo, bar]`，而非继承 `Qux` 里的 `[foo, bar]`。

  继承里，除了第一段以外的后几段可以在继承的 mixin 中寻找属性。

### Qualified This 语法

当需要访问外层 mixin 的动态 `self`（类似 Java 的 `Outer.this`）时，使用显式的 qualified this 语法：

```yaml
- [OuterMixin, [property, path]]
```

这是一个两元素数组：第一个元素是字符串（外层作用域的 `selfName`），第二个元素是非空字符串数组（在该作用域的动态 `self` 上导航的路径）。

**示例**：

```yaml
NatAdd:
  - [types, Nat]
  - augend:
      - [types, Nat]
    addend:
      - [types, Nat]
    _applied_addend:
      - [NatAdd, [addend]]          # Qualified this: NatAdd.self.addend
      - successor:
          - [NatAdd, [successor]]   # Qualified this: NatAdd.self.successor
        zero:
          - [NatAdd, [zero]]        # Qualified this: NatAdd.self.zero
    result:
      - [_applied_addend, result]   # 普通变量引用（不是 qualified this）
```

**何时使用**：
- 当目标属性是通过继承获得的，且在当前作用域中被同名属性遮蔽时，必须使用 qualified this。
- 如果目标属性可以在当前词法域中直接访问（作为自身属性或通过外层作用域），则直接使用 `[property]` 或 `[property, subproperty]` 即可。

## 示例代码

### `math.mixin.yaml`

```yaml
basic:
  Add:
    - [Number]
    - addend1: [Number]
      addend2: [Number]
  Multiply:
    - [Number]
    - multiplicand: [Number]
      multiplier: [Number]

advanced:
  Square:
    - [basic, Multiply]
    - multiplicand: [Number]
      multiplier: [multiplicand]
```

### `Number.mixin.yaml`

```yaml
Equal:
  - [Boolean]
  - other: [Number]
```

### `Assert.mixin.yaml`

```yaml
assertion: [Boolean]
```

### `test_cases.mixin.yaml`

```yaml
math_test:
  - [Assert]
  - _expected: 9
    assertion:
      - [_expected, Equal]
      - other:
          - [math, advanced, Square]
          - multiplicand: 3
```

### 解释示例代码

1. **`math.mixin.yaml`**：

   - 定义了基本的数学操作 `Add` 和 `Multiply` 以及高级操作 `Square`，其中 `Square` 继承了 `Multiply`。

2. **`Number.mixin.yaml`**：

   - 定义了 `Equal` 用于比较两个 `Number` 类型的值是否相等。

3. **`Assert.mixin.yaml`**：

   - 定义了一个 `assertion`，类型为 `Boolean`，用于断言操作。

4. **`test_cases.mixin.yaml`**：

   - 定义了一个测试用例 `math_test`，通过 `Assert` 来验证 `3` 的平方是否等于 `9`。

## 编译器实现

MIXIN 的编译器和解释器分为三个阶段：

### 阶段一：前端

将源码解析为抽象语法树（AST），因为源码是 YAML、JSON 或 TOML 格式，所以解析器直接用现成的库即可。

### 阶段二：中间层

将抽象语法树转换为计算图。mixin 之间的依赖关系通过继承来表示。如果 mixin 之间互相依赖，存在互递归，那么整个计算图是有向有环图。但是每一个 mixin 内部是一个有向无环的子图，其中节点是 mixin 的属性，边是属性之间的依赖关系。

MIXIN 的库提供计算图的反射 API。反射 API 的实际实现计划在 Python/Scala 中完成。

计算图在内存中有两种表示：

1. 支持多重继承和动态定义的类，这些类只有静态属性，没有实例属性。
2. 简单的 Python/Scala 的数据结构而不是动态定义的类，也可以缓存到数据库里。

第一种表示方式比较适合 Python 和 JavaScript。Python 的 C3 线性化虽然和这里的任意多重继承冲突，但 Python 提供了定制 mro 的方法。JavaScript 的 decorator 只要实现了去重逻辑，也能支持多重继承。

第二种方式执行起来更快，因为不需要动态定义的类，而且不依赖编写编译器的语言的特性。可以在任何语言中实现 MIXIN 编译器。

### 阶段三：后端

#### 目标平台

##### 当前支持的平台

- **Nix 平台**：
  - 使用 Nix 编写了 MIXIN 的运行时和 JIT 编译器，将 MIXIN 编译为 Nix 表达式。

##### 尚未支持的平台

- **Scala 平台**：
  - **即时编译器**：
    - 使用 Scala 宏实现，通过“运行时多阶段编程”将 mixin 编译为 Scala trait，并通过反射动态加载。
  - **字节码编译器**：
    - 使用 Scala 宏实现，编译为 TASTy 和 Java 字节码。
  
- **Python 平台**：
  - **即时编译器**：
    - 使用 Python 的 `type` API 和 module loader 动态创建 Python 类。
  - **源到源编译器**：
    - 使用 Python 的 `ast.unparse` API，将 mixin 编译为 Python 源文件。
  
- **JavaScript 平台**：
  - **即时编译器**：
    - 动态创建 JavaScript 的类装饰器。

#### 自举编译器

MIXIN 的后端编译器计划支持自举，因为 MIXIN 运行时不存在多重继承，只依赖很少的目标平台特性。

**注意**：自举编译器的设计尚未完成，具体实现方式仍在规划中。

## 标准库（尚未实现）

MIXIN 标准库计划包含多个模块，用于实现基本的数据结构和功能。以下是计划实现的标准库模块：

- **mixin.rx_v1**：MIXIN 原生实现的 ReactiveX 库。
- **mixin.string_v1**：格式化字符串的最小 API。
- **mixin.list_v1**：定义一个单链表的最小 API。
- **mixin.function_v1**：定义和调用函数的最小 API。
- **mixin.async_v1**：定义和调用异步函数的最小 API。
- **mixin.file.generator_v1**：生成文件和目录的 API。
- **mixin.reflection_v1**：提供反射功能的 API。
- **mixin.utilities**：一些工具函数，如 list 的 map、filter、reduce 等。
  - **mixin.utilities.string_v1**
  - **mixin.utilities.list_v1**
  - **mixin.utilities.function_v1**
- **mixin.ffi**：外部函数接口，支持不同平台。
  - **mixin.ffi.nix_v1**：继承自 `src`，由 Nix 实现。
    - **mixin.ffi.nix_v1.mixin.reflection_v1**
    - **mixin.ffi.nix_v1.mixin.string_v1**
    - **mixin.ffi.nix_v1.mixin.list_v1**
    - **mixin.ffi.nix_v1.mixin.function_v1**
    - **mixin.ffi.nix_v1.mixin.file.generator_v1**
  - **mixin.ffi.current**：指向当前的 FFI 实现，如 `mixin.ffi.nix_v1`。
- **mixin.formats**：格式化库，用 MIXIN 编写。
  - **mixin.formats.json_v1**：支持 `mixin.string_v1` 和 `mixin.list_v1`。
  - **mixin.formats.javascript_v1**：支持 `mixin.string_v1`、`mixin.list_v1`、`mixin.function_v1` 和 `mixin.async_v1`。
  - **mixin.formats.python_v1**：支持 `mixin.string_v1`、`mixin.list_v1`、`mixin.function_v1` 和 `mixin.async_v1`。
  - **mixin.formats.python_ast_v1**：支持 `mixin.string_v1`、`mixin.list_v1`、`mixin.function_v1` 和 `mixin.async_v1`，生成 Python 的 `ast` 模块调用，可以包含行号信息。

**计划**：标准库将以 `monorepo` 形式开发，以便组件之间的依赖和共同演进。每个模块将以 `_v<版本号>` 结尾，以支持版本管理和向后兼容性。

## TODO

以下是未来需要实现的功能和模块划分：

- **运行时优化**：
  - 支持不同的运行时模式选择，如惰性计算、异步计算和 ReactiveX。
  
- **标准库实现**：
  - 按计划实现各个标准库模块，如 `mixin.rx_v1`、`mixin.list_v1`、`mixin.function_v1` 等。
  
- **多目标平台编译器**：
  - 实现针对 Scala、Python、JavaScript 等平台的编译器和即时编译器。
  
- **自举编译器**：
  - 设计和实现自举编译器，使 MIXIN 可以自身编译和扩展。
  
- **测试和文档**：
  - 完善测试用例，确保语言和编译器的稳定性。
  - 更新和完善文档，确保用户能够正确理解和使用 MIXIN。
  
- **性能优化**：
  - 优化编译器和运行时的性能，提升 MIXIN 在各平台上的执行效率。
  
- **社区和贡献指南**：
  - 建立社区，鼓励贡献者参与 MIXIN 的开发和扩展。
  - 制定贡献指南，规范代码贡献和模块扩展的流程。

---

通过以上规划和实施，MIXIN 语言将逐步完善其功能和生态系统，提供一个强大而灵活的多语言互操作性编程平台。

## 与模式的映射

MIXIN 语言规范直接映射到 `mixin.schema.json` 文件中定义的模式，开发者可以使用该模式来验证 MIXIN 文件的格式和结构。请访问 [mixin.schema.json](mixin.schema.json) 获取更多信息。

## 总结

MIXIN 语言通过 mixin 的组合和配置，实现了逻辑和数据结构的统一表达。其设计强调模块化、命名规范和跨平台编译能力，支持多种源码格式和灵活的继承机制。通过明确的命名规范和文件组织策略，MIXIN 语言提高了代码的可读性和可维护性。同时，通过自举编译器设计，确保了语言自身的扩展性和灵活性。

目前，MIXIN 主要通过 Nix 实现其运行时和 JIT 编译器，未来计划支持更多目标平台和完善标准库，进一步增强 MIXIN 的功能和适用范围。
