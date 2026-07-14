import unittest
from src.modules import (
    get_module, MODULES, DEFAULT_MODULE_ID,
    get_module_for_objective_function, OBJECTIVE_FUNCTION_TO_MODULE,
)


class TestModules(unittest.TestCase):
    def test_default_module_is_sport_active_travel(self):
        self.assertEqual(DEFAULT_MODULE_ID, "sport_active_travel")

    def test_get_module_returns_sport_module(self):
        m = get_module("sport_active_travel")
        self.assertEqual(m.id, "sport_active_travel")

    def test_sport_module_includes_original_base_categories(self):
        # Nessuna rottura: le 4 categorie originali restano richieste.
        m = get_module("sport_active_travel")
        for base in ("restaurant", "tourist_attraction", "museum", "park"):
            self.assertIn(base, m.included_place_types)

    def test_sport_module_includes_real_sport_categories(self):
        # [2026-07-11] Il punto centrale del fix: il modulo sport DEVE
        # richiedere categorie sportive reali, altrimenti ENERGY_PACING
        # resta irraggiungibile come scoperto in Fase 3.
        m = get_module("sport_active_travel")
        for sport_type in ("tennis_court", "gym", "sports_complex", "stadium"):
            self.assertIn(sport_type, m.included_place_types)

    def test_all_modules_include_shopping_categories(self):
        # [AGGIUNTO 2026-07-13 (ter) — categoria shopping, confermata come
        # miglioramento generale di prodotto via AskUserQuestion] Shopping
        # vive nel nucleo universale (_BASE_TYPES), non in un modulo
        # verticale dedicato — deve quindi comparire in OGNI modulo, non
        # solo in uno specifico (a differenza di tennis_court/zoo/
        # coworking_space, specifici del proprio modulo).
        for module_id in MODULES:
            m = get_module(module_id)
            for shopping_type in ("gift_shop", "shopping_mall", "market"):
                self.assertIn(
                    shopping_type, m.included_place_types,
                    f"'{shopping_type}' manca nel modulo '{module_id}'",
                )

    def test_unknown_module_raises_value_error(self):
        with self.assertRaises(ValueError):
            get_module("modulo_inesistente")

    def test_default_module_id_used_when_no_arg(self):
        self.assertEqual(get_module().id, DEFAULT_MODULE_ID)

    # [AGGIUNTO 2026-07-11] Secondo modulo verticale: "famiglia_con_bambini".
    def test_get_module_returns_family_module(self):
        m = get_module("famiglia_con_bambini")
        self.assertEqual(m.id, "famiglia_con_bambini")

    def test_family_module_includes_original_base_categories(self):
        m = get_module("famiglia_con_bambini")
        for base in ("restaurant", "tourist_attraction", "museum", "park"):
            self.assertIn(base, m.included_place_types)

    def test_family_module_includes_real_family_categories(self):
        # Verificate sulla tassonomia ufficiale Google Places (fetch diretto
        # della pagina 2026-07-11), non ipotizzate a mano.
        m = get_module("famiglia_con_bambini")
        for family_type in ("zoo", "aquarium", "amusement_park", "water_park"):
            self.assertIn(family_type, m.included_place_types)

    def test_two_modules_are_independent(self):
        # Il modulo famiglia non deve trascinarsi dietro categorie sportive,
        # e viceversa — moduli indipendenti, non un unico elenco condiviso.
        sport = get_module("sport_active_travel")
        family = get_module("famiglia_con_bambini")
        self.assertNotIn("tennis_court", family.included_place_types)
        self.assertNotIn("zoo", sport.included_place_types)

    # [AGGIUNTO 2026-07-11] Terzo modulo verticale: "lavoro_nomadi_digitali".
    def test_get_module_returns_work_module(self):
        m = get_module("lavoro_nomadi_digitali")
        self.assertEqual(m.id, "lavoro_nomadi_digitali")

    def test_work_module_includes_original_base_categories(self):
        m = get_module("lavoro_nomadi_digitali")
        for base in ("restaurant", "tourist_attraction", "museum", "park"):
            self.assertIn(base, m.included_place_types)

    def test_work_module_includes_real_work_categories(self):
        # Verificate sulla tassonomia ufficiale Google Places (fetch diretto
        # della pagina 2026-07-11: tabella "Business" per business_center/
        # coworking_space, non ipotizzate a mano.
        m = get_module("lavoro_nomadi_digitali")
        for work_type in ("coworking_space", "business_center", "library", "internet_cafe"):
            self.assertIn(work_type, m.included_place_types)

    def test_three_modules_are_independent(self):
        sport = get_module("sport_active_travel")
        family = get_module("famiglia_con_bambini")
        work = get_module("lavoro_nomadi_digitali")
        self.assertNotIn("coworking_space", sport.included_place_types)
        self.assertNotIn("coworking_space", family.included_place_types)
        self.assertNotIn("tennis_court", work.included_place_types)
        self.assertNotIn("zoo", work.included_place_types)


class TestGetModuleForObjectiveFunction(unittest.TestCase):
    """[AGGIUNTO 2026-07-11] Regressione diretta per il bug critico:
    pipeline.py::run_live() usava sempre DEFAULT_MODULE_ID (sport)
    indipendentemente da trip.objective_function. Questi test coprono
    esattamente il pezzo di logica che run_live() ora usa al posto
    dell'hardcode."""

    def test_energy_pacing_selects_sport_module(self):
        m = get_module_for_objective_function("ENERGY_PACING")
        self.assertEqual(m.id, "sport_active_travel")

    def test_friction_safety_selects_family_module(self):
        m = get_module_for_objective_function("FRICTION_SAFETY")
        self.assertEqual(m.id, "famiglia_con_bambini")

    def test_work_connectivity_selects_work_module(self):
        m = get_module_for_objective_function("WORK_CONNECTIVITY")
        self.assertEqual(m.id, "lavoro_nomadi_digitali")

    def test_balanced_falls_back_to_default_module(self):
        # Nessun modulo dedicato ancora per BALANCED: fallback esplicito e
        # documentato a DEFAULT_MODULE_ID, non un errore silenzioso.
        m = get_module_for_objective_function("BALANCED")
        self.assertEqual(m.id, DEFAULT_MODULE_ID)

    def test_exclusivity_zero_friction_falls_back_to_default_module(self):
        m = get_module_for_objective_function("EXCLUSIVITY_ZERO_FRICTION")
        self.assertEqual(m.id, DEFAULT_MODULE_ID)

    def test_unknown_objective_function_falls_back_to_default_module(self):
        # Non dovrebbe mai accadere in pratica (Trip.validate() la blocca
        # prima), ma get_module_for_objective_function() non deve esplodere:
        # fallback allo stesso DEFAULT_MODULE_ID.
        m = get_module_for_objective_function("QUALCOSA_DI_INESISTENTE")
        self.assertEqual(m.id, DEFAULT_MODULE_ID)

    def test_mapping_covers_every_valid_objective_function(self):
        # Regressione: se in futuro si aggiunge un quinto objective_function
        # a schemas.VALID_OBJECTIVE_FUNCTIONS senza aggiungerlo anche qui,
        # questo test lo segnala esplicitamente (stesso pattern già usato
        # in test_triage.py per il bug della whitelist desincronizzata).
        from src.schemas import VALID_OBJECTIVE_FUNCTIONS
        for of in VALID_OBJECTIVE_FUNCTIONS:
            self.assertIn(of, OBJECTIVE_FUNCTION_TO_MODULE, f"'{of}' manca in OBJECTIVE_FUNCTION_TO_MODULE")


if __name__ == "__main__":
    unittest.main()
