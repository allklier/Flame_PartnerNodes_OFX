// Every model in the bundle, in plugin order. ofx/src/plugin.cpp must list the same ones (the
// load_bundle test checks); the tests and the JSON dump for the Python contract test use this.
#include "model_spec.h"

namespace cpo {

ModelParam modelParam(ParamKind kind, const char* name, const char* label, const char* hint, int column) {
  ModelParam p;
  p.kind = kind;
  p.name = name;
  p.label = label;
  p.hint = hint;
  p.column = column;
  return p;
}

const std::vector<const ModelSpec*>& allModels() {
  static const std::vector<const ModelSpec*> models = {&krea3Spec(), &nanoBananaProSpec()};
  return models;
}

}  // namespace cpo
