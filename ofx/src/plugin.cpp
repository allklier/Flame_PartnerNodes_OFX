// Partner Models OFX: one OFX plugin per partner model (decision 2). Adding a model = a ModelSpec
// in ofx/src/models/ + worker/cpo/models/<module>.py + one line here.
#include "partner_effect.h"

namespace OFX {
namespace Plugin {
void getPluginIDs(OFX::PluginFactoryArray& ids) {
  // Same models, same order as cpo::allModels() (models/registry.cpp); test_load_bundle checks.
  static cpo::PartnerFactory<&cpo::krea3Spec> krea3;
  static cpo::PartnerFactory<&cpo::nanoBananaProSpec> nanoBananaPro;
  ids.push_back(&krea3);
  ids.push_back(&nanoBananaPro);
}
}  // namespace Plugin
}  // namespace OFX
